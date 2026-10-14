"""Canonical prepared-selection execution for the teacher Reports menu.

This module is the in-process adapter between the small guided-selection
contract and the eight existing report engines.  It does not shell out to the
CLI, author academic state, or create report files.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias

from pds_core.academic_catalog import (
    AcademicPeriodCatalogQuery,
    CatalogAcademicPeriod,
    query_academic_period_catalog,
)
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.classes import list_class_folders
from pds_core.workspace import resolve_workspace_root

from meridian.academic_period_proficiency_storage import (
    list_current_academic_period_proficiency_results,
)
from meridian.assessment_impact import build_assessment_impact
from meridian.class_standards_profile import build_current_class_standards_profile
from meridian.diagnostics import DiagnosticsDependencies
from meridian.evidence_coverage import build_current_evidence_coverage
from meridian.external_gradebook_mapping import (
    external_gradebook_mapping_from_json_bytes,
)
from meridian.grade_checkpoint_comparison import (
    build_snapshot_to_current_grade_checkpoint_comparison,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.marking_period_readiness import build_marking_period_readiness
from meridian.proficiency_mapping_storage import load_proficiency_scale_revision
from meridian.report_guided_selection import ReportPreparedSelection, ReportScope
from meridian.reporting_snapshot_record import ReportingSnapshotBuildRequest
from meridian.reporting_snapshot_selection import (
    load_current_reporting_snapshot_selection,
)
from meridian.reporting_snapshot_storage import (
    StoredReportingSnapshot,
    list_reporting_snapshot_ids,
    load_reporting_snapshot,
)
from meridian.reporting_snapshot_workflow import (
    ReportingSnapshotProjectionAuthorization,
    required_projection_authorizations,
)
from meridian.sis_gradebook_reconciliation import (
    build_sis_gradebook_reconciliation,
    current_proficiency_observation,
)
from meridian.student_grade_justification import (
    build_snapshot_student_grade_justification,
)
from meridian.student_proficiency_growth import build_student_proficiency_growth
from meridian.teacher_report import TeacherReportPreview

WorkspaceResolver: TypeAlias = Callable[[], Path]
Clock: TypeAlias = Callable[[], datetime]


class ReportMenuExecutionError(RuntimeError):
    """One guided report could not be built from exact current authority."""

    code = "teacher_reports.execution_failed"


class ReportMenuSelectionChangedError(ReportMenuExecutionError):
    """A material guided selector moved while a report was generated."""

    code = "teacher_reports.selection_changed"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ReportMenuExecutionDependencies:
    workspace_resolver: WorkspaceResolver = resolve_workspace_root
    clock: Clock = _utc_now
    diagnostics: DiagnosticsDependencies | None = None


@dataclass(frozen=True, slots=True)
class _Context:
    root: Path
    class_id: str
    period: CatalogAcademicPeriod
    identifiers: dict[ReportScope, str]
    report_kind: str


@dataclass(slots=True)
class LiveReportMenuExecutor:
    """Execute all eight guided report families through their canonical engines."""

    dependencies: ReportMenuExecutionDependencies = ReportMenuExecutionDependencies()

    def build(self, prepared: ReportPreparedSelection) -> TeacherReportPreview:
        try:
            context = self._context(prepared)
            before = self._selection_witness(context)
            generated_at = self.dependencies.clock().astimezone(UTC)
            preview = self._build(context, prepared.report_kind, generated_at)
            after = self._selection_witness(self._context(prepared))
        except ReportMenuExecutionError:
            raise
        except (OSError, RuntimeError, StopIteration, ValueError) as error:
            raise ReportMenuExecutionError(
                "The selected report could not be generated from verified current "
                "records. Refresh the choices and try again."
            ) from error
        if after != before:
            raise ReportMenuSelectionChangedError(
                "The class, period, student, assessment, checkpoint, or mapping "
                "changed during report generation. Refresh the choices and try again."
            )
        return preview

    def revalidate(
        self,
        prepared: ReportPreparedSelection,
        preview: TeacherReportPreview | None = None,
    ) -> None:
        """Recheck material selection authority immediately before local save."""

        try:
            context = self._context(prepared)
            self._selection_witness(context)
            if preview is not None:
                rebuilt = self._build(
                    context,
                    prepared.report_kind,
                    preview.generated_at,
                )
                if rebuilt.preview_sha256 != preview.preview_sha256:
                    raise ReportMenuSelectionChangedError(
                        "The report sources changed after preview. Refresh before "
                        "saving."
                    )
        except ReportMenuExecutionError:
            raise
        except (OSError, RuntimeError, StopIteration, ValueError) as error:
            raise ReportMenuExecutionError(
                "The selected report sources could not be revalidated."
            ) from error

    def _context(self, prepared: ReportPreparedSelection) -> _Context:
        identifiers = prepared.identifiers()
        class_id = identifiers.get("class")
        period_id = identifiers.get("period")
        if class_id is None or period_id is None:
            raise ReportMenuExecutionError(
                "The report selection is missing its class or marking period."
            )
        root = self.dependencies.workspace_resolver().resolve(strict=True)
        folders = tuple(
            item
            for item in list_class_folders(
                root,
                require_metadata=True,
                load_metadata=True,
            )
            if item.class_id == class_id and item.metadata is not None
        )
        if len(folders) != 1:
            raise ReportMenuExecutionError(
                "The selected class is no longer available. Refresh the choices."
            )
        metadata = folders[0].metadata
        assert metadata is not None
        periods = tuple(
            item
            for item in query_academic_period_catalog(
                root,
                AcademicPeriodCatalogQuery(
                    school_year=metadata.school_year,
                    period_type="marking_period",
                    current_calendar_only=True,
                ),
            )
            if item.period_id == period_id and item.lifecycle != "cancelled"
        )
        if len(periods) != 1:
            raise ReportMenuExecutionError(
                "The selected marking period is no longer available. Refresh the "
                "choices."
            )
        return _Context(root, class_id, periods[0], identifiers, prepared.report_kind)

    def _build(
        self,
        context: _Context,
        report_kind: str,
        generated_at: datetime,
    ) -> TeacherReportPreview:
        period = AcademicPeriodRef(
            context.period.school_year,
            context.period.period_id,
        )
        if report_kind == "sis_gradebook_reconciliation":
            return self._reconciliation(context, generated_at)
        if report_kind == "student_current_grade_justification":
            stored = self._checkpoint(context)
            student_id = self._required(context, "student")
            return build_snapshot_student_grade_justification(
                context.root,
                stored.reference,
                student_id,
                generated_at=generated_at,
            )
        if report_kind == "class_standards_profile":
            return build_current_class_standards_profile(
                context.root,
                class_id=context.class_id,
                target_period=period,
                calendar_revision=context.period.calendar_revision,
                generated_at=generated_at,
            )
        if report_kind == "student_proficiency_growth":
            return build_student_proficiency_growth(
                context.root,
                class_id=context.class_id,
                student_id=self._required(context, "student"),
                target_period=period,
                calendar_revision=context.period.calendar_revision,
                generated_at=generated_at,
            )
        if report_kind == "evidence_coverage":
            return build_current_evidence_coverage(
                context.root,
                class_id=context.class_id,
                target_period=period,
                calendar_revision=context.period.calendar_revision,
                generated_at=generated_at,
            )
        if report_kind == "grade_checkpoint_comparison":
            stored = self._checkpoint(context)
            request = stored.snapshot.build_request
            return build_snapshot_to_current_grade_checkpoint_comparison(
                context.root,
                prior_reference=stored.reference,
                current_build_request=request,
                authorizations=_authorizations(request),
                generated_at=generated_at,
                dependencies=self.dependencies.diagnostics,
            )
        if report_kind == "marking_period_readiness":
            request = self._checkpoint(context).snapshot.build_request
            return build_marking_period_readiness(
                context.root,
                build_request=request,
                authorizations=_authorizations(request),
                generated_at=generated_at,
                dependencies=self.dependencies.diagnostics,
            )
        if report_kind == "assessment_impact":
            request = self._checkpoint(context).snapshot.build_request
            return build_assessment_impact(
                context.root,
                grade_item_id=self._required(context, "grade_item"),
                build_request=request,
                authorizations=_authorizations(request),
                generated_at=generated_at,
                dependencies=self.dependencies.diagnostics,
            )
        raise ReportMenuExecutionError("The selected report family is unsupported.")

    def _reconciliation(
        self,
        context: _Context,
        generated_at: datetime,
    ) -> TeacherReportPreview:
        path = Path(self._required(context, "mapping"))
        content = _bounded_file(path, 512 * 1024)
        profile = external_gradebook_mapping_from_json_bytes(content)
        if (
            profile.class_id != context.class_id
            or profile.target_period.school_year != context.period.school_year
            or profile.target_period.period_id != context.period.period_id
        ):
            raise ReportMenuExecutionError(
                "The selected mapping no longer matches the class and period."
            )
        scale = load_proficiency_scale_revision(
            context.root,
            context.class_id,
            profile.target_scale.scale_id,
            profile.target_scale.scale_revision,
        ).scale
        stored = list_current_academic_period_proficiency_results(
            context.root,
            context.class_id,
            context.period.school_year,
            context.period.period_id,
        )
        observations = tuple(current_proficiency_observation(item) for item in stored)
        built = build_sis_gradebook_reconciliation(
            class_id=context.class_id,
            target_period=AcademicPeriodRef(
                context.period.school_year,
                context.period.period_id,
            ),
            calendar_revision=context.period.calendar_revision,
            target_scale=scale,
            mapping_profile=profile,
            current_observations=observations,
            generated_at=generated_at,
            changed_only=False,
        )
        final = tuple(
            current_proficiency_observation(item)
            for item in list_current_academic_period_proficiency_results(
                context.root,
                context.class_id,
                context.period.school_year,
                context.period.period_id,
            )
        )
        if final != observations or _bounded_file(path, 512 * 1024) != content:
            raise ReportMenuSelectionChangedError(
                "The proficiency or mapping basis changed during reconciliation."
            )
        return built.display_preview

    def _checkpoint(self, context: _Context) -> StoredReportingSnapshot:
        snapshot_id = context.identifiers.get("checkpoint")
        if snapshot_id is not None:
            stored = load_reporting_snapshot(
                context.root,
                context.class_id,
                snapshot_id,
            )
        else:
            selected: dict[str, StoredReportingSnapshot] = {}
            for candidate_id in list_reporting_snapshot_ids(
                context.root,
                context.class_id,
            ):
                candidate = load_reporting_snapshot(
                    context.root,
                    context.class_id,
                    candidate_id,
                )
                snapshot = candidate.snapshot
                if (
                    snapshot.target_period.school_year
                    != context.period.school_year
                    or snapshot.target_period.period_id != context.period.period_id
                    or snapshot.calendar_revision
                    != context.period.calendar_revision
                ):
                    continue
                current = load_current_reporting_snapshot_selection(
                    context.root,
                    context.class_id,
                    snapshot.definition_reference.definition_id,
                    snapshot.target_period,
                    snapshot.calendar_revision,
                )
                if (
                    current is not None
                    and current.selection.snapshot_reference == candidate.reference
                ):
                    selected[candidate.snapshot_sha256] = candidate
            if len(selected) != 1:
                raise ReportMenuExecutionError(
                    "Choose one exact current-use checkpoint in Snapshots before "
                    "running this report."
                )
            stored = next(iter(selected.values()))
        snapshot = stored.snapshot
        if (
            snapshot.target_period.school_year != context.period.school_year
            or snapshot.target_period.period_id != context.period.period_id
            or snapshot.calendar_revision != context.period.calendar_revision
        ):
            raise ReportMenuExecutionError(
                "The checkpoint no longer matches the selected marking period."
            )
        return stored

    @staticmethod
    def _required(context: _Context, scope: ReportScope) -> str:
        value = context.identifiers.get(scope)
        if value is None:
            raise ReportMenuExecutionError(
                f"The report selection is missing required {scope} context."
            )
        return value

    def _selection_witness(self, context: _Context) -> str:
        pieces: list[object] = [
            str(context.root),
            context.class_id,
            context.period.school_year,
            context.period.period_id,
            context.period.calendar_revision,
            context.period.lifecycle,
        ]
        folder = next(
            item
            for item in list_class_folders(
                context.root,
                require_metadata=True,
                load_metadata=True,
            )
            if item.class_id == context.class_id
        )
        pieces.append(_file_sha256(folder.metadata_path))
        if "student" in context.identifiers:
            pieces.append(_file_sha256(folder.roster_path))
        grade_item_id = context.identifiers.get("grade_item")
        if grade_item_id is not None:
            grade_item = load_current_grade_item_revision(
                context.root,
                context.class_id,
                grade_item_id,
            )
            if grade_item is None:
                raise ReportMenuExecutionError(
                    "The selected assignment no longer has a current revision."
                )
            pieces.append(grade_item.revision_sha256)
        checkpoint_reports = {
            "student_current_grade_justification",
            "grade_checkpoint_comparison",
            "marking_period_readiness",
            "assessment_impact",
        }
        if context.report_kind in checkpoint_reports:
            pieces.append(self._checkpoint(context).snapshot_sha256)
        mapping = context.identifiers.get("mapping")
        if mapping is not None:
            mapping_bytes = _bounded_file(Path(mapping), 512 * 1024)
            pieces.append(hashlib.sha256(mapping_bytes).hexdigest())
        encoded = json.dumps(pieces, ensure_ascii=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def _authorizations(
    request: ReportingSnapshotBuildRequest,
) -> tuple[ReportingSnapshotProjectionAuthorization, ...]:
    students: dict[tuple[str, str], set[str]] = {}
    for grade_request in request.grade_requests:
        for evidence in grade_request.work_evidence or ():
            for reference in evidence.projection_snapshots:
                students.setdefault(
                    (reference.publication_id, reference.cache_key), set()
                ).add(grade_request.target.student_id)
    return tuple(
        ReportingSnapshotProjectionAuthorization(
            publication_id=reference.publication_id,
            cache_key=reference.cache_key,
            purpose_id="teacher_reporting",
            student_ids=tuple(
                sorted(students[(reference.publication_id, reference.cache_key)])
            ),
        )
        for reference in required_projection_authorizations(request)
    )


def _bounded_file(path: Path, maximum: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ReportMenuExecutionError(
            "The selected input must be a regular non-linked file."
        )
    if path.stat().st_size > maximum:
        raise ReportMenuExecutionError("The selected input exceeds its size limit.")
    content = path.read_bytes()
    if len(content) > maximum:
        raise ReportMenuExecutionError("The selected input exceeds its size limit.")
    return content


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(_bounded_file(path, 2 * 1024 * 1024)).hexdigest()


__all__ = (
    "LiveReportMenuExecutor",
    "ReportMenuExecutionDependencies",
    "ReportMenuExecutionError",
    "ReportMenuSelectionChangedError",
)
