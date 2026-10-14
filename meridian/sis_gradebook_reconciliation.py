"""Vendor-neutral SIS gradebook reconciliation over selected proficiency state."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef, validate_academic_period_ref
from pds_core.identifiers import IdentifierValidationError, validate_identifier

from meridian.academic_period_proficiency_storage import (
    StoredAcademicPeriodProficiencyResult,
)
from meridian.external_gradebook_mapping import (
    ExternalGradebookMappingReference,
    ExternalGradebookMappingRevision,
    external_gradebook_mapping_reference,
    external_gradebook_value,
    validate_external_gradebook_mapping_against_scale,
)
from meridian.proficiency_mapping import ProficiencyScale, ProficiencyScaleReference
from meridian.teacher_report import (
    TeacherReportColumn,
    TeacherReportDiagnostic,
    TeacherReportPreview,
    TeacherReportRow,
    TeacherReportSourceReference,
    compose_teacher_report_preview,
    validate_teacher_report_preview,
)

ReconciliationChangeState: TypeAlias = Literal[
    "NEW",
    "CHANGED",
    "UNCHANGED",
    "REVIEW_REQUIRED",
]
CurrentProficiencyStatus: TypeAlias = Literal[
    "calculated",
    "insufficient_evidence",
]

_FULL_CHECKPOINT_DIAGNOSTIC: Final[str] = "reconciliation.full_checkpoint"
_CHANGED_ONLY_DIAGNOSTIC: Final[str] = "reconciliation.changed_only_view"
_SHA256: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}$")


class SisGradebookReconciliationError(ValueError):
    """Base error for SIS reconciliation derivation."""

    code = "sis_reconciliation.error"


class SisGradebookReconciliationValidationError(SisGradebookReconciliationError):
    """Raised when source state cannot be reconciled safely."""

    code = "sis_reconciliation.invalid"


@dataclass(frozen=True, slots=True)
class CurrentProficiencyObservation:
    """Exact selected Academic Period proficiency result projected for reporting."""

    class_id: str
    target_period: AcademicPeriodRef
    calendar_revision: int
    student_id: str
    standard_id: str
    result_revision: int
    result_sha256: str
    target_scale: ProficiencyScaleReference
    status: CurrentProficiencyStatus
    proficiency_level_id: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "class_id", _identifier(self.class_id, "class_id"))
        if not isinstance(self.target_period, AcademicPeriodRef):
            raise SisGradebookReconciliationValidationError(
                "target_period must be an AcademicPeriodRef."
            )
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
        object.__setattr__(
            self,
            "standard_id",
            _standard_id(self.standard_id),
        )
        object.__setattr__(
            self,
            "result_revision",
            _positive_int(self.result_revision, "result_revision"),
        )
        object.__setattr__(
            self,
            "result_sha256",
            _sha256(self.result_sha256, "result_sha256"),
        )
        if not isinstance(self.target_scale, ProficiencyScaleReference):
            raise SisGradebookReconciliationValidationError(
                "target_scale must be a ProficiencyScaleReference."
            )
        if self.target_scale.class_id != self.class_id:
            raise SisGradebookReconciliationValidationError(
                "target_scale must match observation class."
            )
        if self.status not in {"calculated", "insufficient_evidence"}:
            raise SisGradebookReconciliationValidationError(
                "unsupported current proficiency status."
            )
        level = self.proficiency_level_id
        if level is not None:
            level = _identifier(level, "proficiency_level_id")
        if self.status == "calculated" and level is None:
            raise SisGradebookReconciliationValidationError(
                "calculated observation requires a proficiency level."
            )
        if self.status == "insufficient_evidence" and level is not None:
            raise SisGradebookReconciliationValidationError(
                "insufficient observation must not carry a proficiency level."
            )
        object.__setattr__(self, "proficiency_level_id", level)


@dataclass(frozen=True, slots=True)
class BuiltSisGradebookReconciliation:
    """Teacher display preview plus complete checkpoint for future comparison."""

    display_preview: TeacherReportPreview
    checkpoint_preview: TeacherReportPreview

    def __post_init__(self) -> None:
        display = validate_teacher_report_preview(self.display_preview)
        checkpoint = validate_reconciliation_checkpoint(self.checkpoint_preview)
        if display.class_id != checkpoint.class_id:
            raise SisGradebookReconciliationValidationError(
                "display and checkpoint class scopes must match."
            )
        if display.target_period != checkpoint.target_period:
            raise SisGradebookReconciliationValidationError(
                "display and checkpoint periods must match."
            )
        if display.calendar_revision != checkpoint.calendar_revision:
            raise SisGradebookReconciliationValidationError(
                "display and checkpoint calendar revisions must match."
            )
        object.__setattr__(self, "display_preview", display)
        object.__setattr__(self, "checkpoint_preview", checkpoint)


def current_proficiency_observation(
    stored: StoredAcademicPeriodProficiencyResult,
) -> CurrentProficiencyObservation:
    """Project one verified selected stored result into bounded report input."""

    if not isinstance(stored, StoredAcademicPeriodProficiencyResult):
        raise SisGradebookReconciliationValidationError(
            "stored result must be a StoredAcademicPeriodProficiencyResult."
        )
    stored.__post_init__()
    snapshot = stored.snapshot
    period = snapshot.target_period.period
    return CurrentProficiencyObservation(
        class_id=snapshot.class_id,
        target_period=AcademicPeriodRef(period.school_year, period.period_id),
        calendar_revision=snapshot.target_period.calendar_revision,
        student_id=snapshot.student_id,
        standard_id=snapshot.standard_id,
        result_revision=snapshot.result_revision,
        result_sha256=stored.result_sha256,
        target_scale=snapshot.target_scale,
        status=snapshot.outcome.status,
        proficiency_level_id=snapshot.outcome.proficiency_level_id,
    )


def build_sis_gradebook_reconciliation(
    *,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    target_scale: ProficiencyScale,
    mapping_profile: ExternalGradebookMappingRevision,
    current_observations: tuple[CurrentProficiencyObservation, ...],
    generated_at: datetime,
    prior_checkpoint: TeacherReportPreview | None = None,
    changed_only: bool = False,
) -> BuiltSisGradebookReconciliation:
    """Build full/current and changed-only views without creating academic state."""

    checked_class = _identifier(class_id, "class_id")
    checked_period = validate_academic_period_ref(target_period)
    checked_calendar = _positive_int(calendar_revision, "calendar_revision")
    if not isinstance(target_scale, ProficiencyScale):
        raise SisGradebookReconciliationValidationError(
            "target_scale must be a ProficiencyScale."
        )
    target_scale.__post_init__()
    if target_scale.class_id != checked_class:
        raise SisGradebookReconciliationValidationError(
            "target scale must match report class."
        )
    profile = validate_external_gradebook_mapping_against_scale(
        mapping_profile,
        target_scale,
    )
    if profile.class_id != checked_class or profile.target_period != checked_period:
        raise SisGradebookReconciliationValidationError(
            "mapping profile must match the exact report class and period."
        )

    observations = _current_observations(
        current_observations,
        checked_class,
        checked_period,
        checked_calendar,
        profile.target_scale,
    )
    prior = (
        {}
        if prior_checkpoint is None
        else _prior_rows(
            prior_checkpoint,
            checked_class,
            checked_period,
            checked_calendar,
            profile.target_scale,
        )
    )
    level_labels = {item.level_id: item.label for item in target_scale.levels}
    current = {(item.student_id, item.standard_id): item for item in observations}
    keys = tuple(sorted(set(current) | set(prior)))

    rows: list[TeacherReportRow] = []
    for student_id, standard_id in keys:
        observation = current.get((student_id, standard_id))
        prior_row = prior.get((student_id, standard_id))
        rows.append(
            _reconciliation_row(
                student_id=student_id,
                standard_id=standard_id,
                current=observation,
                prior=prior_row,
                level_labels=level_labels,
                mapping_profile=profile,
            )
        )

    source_references = _source_references(
        observations,
        profile,
        prior_checkpoint,
    )
    columns = _columns(profile.system_label)
    checkpoint = compose_teacher_report_preview(
        report_kind="sis_gradebook_reconciliation",
        title=f"SIS Gradebook Reconciliation — {profile.system_label}",
        class_id=checked_class,
        target_period=checked_period,
        calendar_revision=checked_calendar,
        source_references=source_references,
        generated_at=generated_at,
        summary=(
            "View: full current reconciliation checkpoint.",
            "Unassessed standards are absent; no missing judgment is "
            "converted to a low value.",
        ),
        columns=columns,
        rows=rows,
        diagnostics=(
            TeacherReportDiagnostic(
                _FULL_CHECKPOINT_DIAGNOSTIC,
                "info",
                "Complete reconciliation checkpoint for exact future comparison.",
            ),
        ),
    )
    if not changed_only:
        return BuiltSisGradebookReconciliation(checkpoint, checkpoint)

    changed_rows = tuple(row for row in rows if row.values[-1] != "UNCHANGED")
    display = compose_teacher_report_preview(
        report_kind="sis_gradebook_reconciliation",
        title=f"SIS Gradebook Reconciliation — {profile.system_label}",
        class_id=checked_class,
        target_period=checked_period,
        calendar_revision=checked_calendar,
        source_references=source_references,
        generated_at=generated_at,
        summary=(
            "View: changed-only teacher convenience view.",
            "The separately generated checkpoint retains the complete current state.",
        ),
        columns=columns,
        rows=changed_rows,
        diagnostics=(
            TeacherReportDiagnostic(
                _CHANGED_ONLY_DIAGNOSTIC,
                "info",
                "UNCHANGED rows are omitted from this display view only.",
            ),
        ),
    )
    return BuiltSisGradebookReconciliation(display, checkpoint)


def validate_reconciliation_checkpoint(
    value: TeacherReportPreview,
) -> TeacherReportPreview:
    """Require a complete full-current reconciliation preview as a checkpoint."""

    preview = validate_teacher_report_preview(value)
    if preview.report_kind != "sis_gradebook_reconciliation":
        raise SisGradebookReconciliationValidationError(
            "prior checkpoint must be a SIS gradebook reconciliation preview."
        )
    if _FULL_CHECKPOINT_DIAGNOSTIC not in {item.code for item in preview.diagnostics}:
        raise SisGradebookReconciliationValidationError(
            "prior reconciliation input is not a complete full-current checkpoint."
        )
    expected = tuple(item.column_id for item in _columns("External gradebook"))
    actual = tuple(item.column_id for item in preview.columns)
    if actual != expected:
        raise SisGradebookReconciliationValidationError(
            "prior reconciliation checkpoint uses an incompatible column contract."
        )
    return preview


def _current_observations(
    values: tuple[CurrentProficiencyObservation, ...],
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    target_scale: ProficiencyScaleReference,
) -> tuple[CurrentProficiencyObservation, ...]:
    if not isinstance(values, tuple):
        raise SisGradebookReconciliationValidationError(
            "current_observations must be a tuple."
        )
    checked = tuple(
        CurrentProficiencyObservation(
            class_id=item.class_id,
            target_period=item.target_period,
            calendar_revision=item.calendar_revision,
            student_id=item.student_id,
            standard_id=item.standard_id,
            result_revision=item.result_revision,
            result_sha256=item.result_sha256,
            target_scale=item.target_scale,
            status=item.status,
            proficiency_level_id=item.proficiency_level_id,
        )
        for item in values
    )
    keys = tuple((item.student_id, item.standard_id) for item in checked)
    if len(set(keys)) != len(keys):
        raise SisGradebookReconciliationValidationError(
            "current observations must not duplicate student/standard identity."
        )
    for item in checked:
        if (
            item.class_id != class_id
            or item.target_period != target_period
            or item.calendar_revision != calendar_revision
        ):
            raise SisGradebookReconciliationValidationError(
                "current observation does not match report scope."
            )
        if item.target_scale != target_scale:
            raise SisGradebookReconciliationValidationError(
                "current observation does not match the exact mapping scale."
            )
    return tuple(sorted(checked, key=lambda item: (item.student_id, item.standard_id)))


def _prior_rows(
    preview: TeacherReportPreview,
    class_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    target_scale: ProficiencyScaleReference,
) -> dict[tuple[str, str], tuple[str, str]]:
    prior = validate_reconciliation_checkpoint(preview)
    if (
        prior.class_id != class_id
        or prior.target_period != target_period
        or prior.calendar_revision != calendar_revision
    ):
        raise SisGradebookReconciliationValidationError(
            "prior checkpoint does not match the exact reconciliation scope."
        )
    scale_sources = [
        item
        for item in prior.source_references
        if item.source_kind == "proficiency_scale"
    ]
    if (
        len(scale_sources) != 1
        or scale_sources[0].source_sha256 != target_scale.scale_sha256
    ):
        raise SisGradebookReconciliationValidationError(
            "prior checkpoint does not match the exact proficiency scale."
        )
    indexes = {item.column_id: index for index, item in enumerate(prior.columns)}
    result: dict[tuple[str, str], tuple[str, str]] = {}
    for row in prior.rows:
        student_id = row.values[indexes["student_id"]]
        standard_id = row.values[indexes["standard_id"]]
        level_id = row.values[indexes["current_proficiency_level_id"]]
        external_value = row.values[indexes["external_value"]]
        if level_id is None or external_value is None:
            level_id = row.values[indexes["prior_proficiency_level_id"]]
            external_value = row.values[indexes["prior_external_value"]]
        if student_id is None or standard_id is None:
            raise SisGradebookReconciliationValidationError(
                "prior checkpoint row lacks durable identity."
            )
        if level_id is None or external_value is None:
            continue
        key = (student_id, standard_id)
        if key in result:
            raise SisGradebookReconciliationValidationError(
                "prior checkpoint duplicates student/standard identity."
            )
        result[key] = (level_id, external_value)
    return result


def _reconciliation_row(
    *,
    student_id: str,
    standard_id: str,
    current: CurrentProficiencyObservation | None,
    prior: tuple[str, str] | None,
    level_labels: dict[str, str],
    mapping_profile: ExternalGradebookMappingRevision,
) -> TeacherReportRow:
    current_level: str | None = None
    current_label: str | None = None
    current_external: str | None = None
    if current is not None and current.status == "calculated":
        assert current.proficiency_level_id is not None
        current_level = current.proficiency_level_id
        try:
            current_label = level_labels[current_level]
        except KeyError as error:
            raise SisGradebookReconciliationValidationError(
                "current result identifies a level outside the exact scale."
            ) from error
        current_external = external_gradebook_value(mapping_profile, current_level)

    prior_level = None if prior is None else prior[0]
    prior_external = None if prior is None else prior[1]
    prior_label = None
    if prior_level is not None:
        try:
            prior_label = level_labels[prior_level]
        except KeyError as error:
            raise SisGradebookReconciliationValidationError(
                "prior checkpoint identifies a level outside the exact scale."
            ) from error

    if current_level is None:
        state: ReconciliationChangeState = "REVIEW_REQUIRED"
    elif prior is None:
        state = "NEW"
    elif current_level == prior_level and current_external == prior_external:
        state = "UNCHANGED"
    else:
        state = "CHANGED"

    row_id = (
        "reconcile_"
        + hashlib.sha256(f"{student_id}\0{standard_id}".encode("utf-8")).hexdigest()
    )
    return TeacherReportRow(
        row_id=row_id,
        values=(
            student_id,
            standard_id,
            current_label,
            current_level,
            current_external,
            prior_label,
            prior_level,
            prior_external,
            state,
        ),
    )


def _columns(system_label: str) -> tuple[TeacherReportColumn, ...]:
    return (
        TeacherReportColumn("student_id", "Student ID"),
        TeacherReportColumn("standard_id", "Standard"),
        TeacherReportColumn("current_proficiency", "Current Proficiency"),
        TeacherReportColumn(
            "current_proficiency_level_id",
            "Current Proficiency Level ID",
        ),
        TeacherReportColumn("external_value", f"{system_label} Value"),
        TeacherReportColumn("prior_proficiency", "Prior Proficiency"),
        TeacherReportColumn(
            "prior_proficiency_level_id",
            "Prior Proficiency Level ID",
        ),
        TeacherReportColumn("prior_external_value", "Prior External Value"),
        TeacherReportColumn("change_state", "Change State"),
    )


def _source_references(
    current: tuple[CurrentProficiencyObservation, ...],
    profile: ExternalGradebookMappingRevision,
    prior_checkpoint: TeacherReportPreview | None,
) -> tuple[TeacherReportSourceReference, ...]:
    profile_ref: ExternalGradebookMappingReference = (
        external_gradebook_mapping_reference(profile)
    )
    sources: list[TeacherReportSourceReference] = [
        TeacherReportSourceReference(
            "external_gradebook_mapping",
            f"{profile_ref.profile_id}:r{profile_ref.profile_revision}",
            profile_ref.profile_sha256,
        ),
        TeacherReportSourceReference(
            "proficiency_scale",
            f"{profile.target_scale.scale_id}:r{profile.target_scale.scale_revision}",
            profile.target_scale.scale_sha256,
        ),
    ]
    for item in current:
        sources.append(
            TeacherReportSourceReference(
                "academic_period_proficiency_result",
                (f"{item.student_id}:{item.standard_id}:r{item.result_revision}"),
                item.result_sha256,
            )
        )
    if prior_checkpoint is not None:
        prior = validate_reconciliation_checkpoint(prior_checkpoint)
        sources.append(
            TeacherReportSourceReference(
                "prior_reconciliation_checkpoint",
                prior.preview_sha256,
                prior.preview_sha256,
            )
        )
    return tuple(sources)


def _identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise SisGradebookReconciliationValidationError(
            f"{field_name} must be a string."
        )
    try:
        return validate_identifier(value, field_name)
    except IdentifierValidationError as error:
        raise SisGradebookReconciliationValidationError(str(error)) from error


def _standard_id(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise SisGradebookReconciliationValidationError(
            "standard_id must be nonblank text without surrounding whitespace."
        )
    if any(ord(character) < 32 for character in value):
        raise SisGradebookReconciliationValidationError(
            "standard_id must not contain control characters."
        )
    return value


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SisGradebookReconciliationValidationError(
            f"{field_name} must be a positive integer."
        )
    return value


def _sha256(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise SisGradebookReconciliationValidationError(
            f"{field_name} must be a lowercase SHA-256 digest."
        )
    return value


__all__ = [
    "BuiltSisGradebookReconciliation",
    "CurrentProficiencyObservation",
    "ReconciliationChangeState",
    "SisGradebookReconciliationError",
    "SisGradebookReconciliationValidationError",
    "build_sis_gradebook_reconciliation",
    "current_proficiency_observation",
    "validate_reconciliation_checkpoint",
]
