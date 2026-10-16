"""Canonical prepared-selection execution for the teacher Reports menu.

This module is the in-process adapter between the small guided-selection
contract and the existing report engines.  It does not shell out to the
CLI, author academic state, or create report files.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeAlias

from pds_core.academic_catalog import (
    AcademicPeriodCatalogQuery,
    CatalogAcademicPeriod,
    query_academic_period_catalog,
)
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.classes import list_class_folders, load_class_roster
from pds_core.routing_models import ModuleWorkRef
from pds_core.workspace import resolve_workspace_root

from meridian.academic_period_proficiency_storage import (
    list_current_academic_period_proficiency_results,
)
from meridian.assessment_impact import build_assessment_impact
from meridian.benchmark_analysis import (
    BenchmarkItemObservation,
    BenchmarkResultStatus,
    BenchmarkStandardObservation,
    BenchmarkStudentResult,
    compose_benchmark_analysis,
)
from meridian.benchmark_current_analysis import build_current_benchmark_analysis
from meridian.class_standards_profile import build_current_class_standards_profile
from meridian.diagnostics import DiagnosticsDependencies
from meridian.evidence import (
    EvidenceItem,
    NativePointValue,
    NativeScalarValue,
    NativeStateValue,
)
from meridian.evidence_coverage import build_current_evidence_coverage
from meridian.external_gradebook_mapping import (
    external_gradebook_mapping_from_json_bytes,
)
from meridian.grade_checkpoint_comparison import (
    build_snapshot_to_current_grade_checkpoint_comparison,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.marking_period_readiness import build_marking_period_readiness
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.proficiency_mapping_storage import (
    list_proficiency_scale_ids,
    load_current_proficiency_scale,
    load_proficiency_scale_revision,
)
from meridian.projection_cache import (
    ProjectionCacheError,
    load_authorized_projection_snapshot,
)
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
from meridian.standards_proficiency_storage import (
    StoredStandardProficiencyResult,
    load_current_standard_proficiency_result,
)
from meridian.student_grade_justification import (
    build_snapshot_student_grade_justification,
)
from meridian.student_proficiency_growth import build_student_proficiency_growth
from meridian.teacher_report import TeacherReportPreview, TeacherReportSourceReference

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
    """Execute guided report families through their canonical engines."""

    dependencies: ReportMenuExecutionDependencies = ReportMenuExecutionDependencies()

    def build(self, prepared: ReportPreparedSelection) -> TeacherReportPreview:
        try:
            context = self._context(prepared)
            before = self._selection_witness(context)
            generated_at = self.dependencies.clock().astimezone(UTC)
            preview = self._build(context, prepared.report_kind, generated_at)
            if prepared.report_kind == "benchmark_analysis_instructional_response":
                reobserved = self._build(
                    context, prepared.report_kind, generated_at
                )
                if reobserved.preview_sha256 != preview.preview_sha256:
                    raise ReportMenuSelectionChangedError(
                        "The benchmark evidence changed during report generation. "
                        "Refresh the choices and try again."
                    )
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
        if report_kind == "benchmark_analysis_instructional_response":
            return build_current_benchmark_analysis(
                context.root,
                class_id=context.class_id,
                grade_item_id=self._required(context, "grade_item"),
                target_period=period,
                calendar_revision=context.period.calendar_revision,
                generated_at=generated_at,
                diagnostics=self.dependencies.diagnostics,
                item_observer=_benchmark_item_observations,
            )
        raise ReportMenuExecutionError("The selected report family is unsupported.")

    def _benchmark(
        self,
        context: _Context,
        generated_at: datetime,
    ) -> TeacherReportPreview:
        """Build a conservative planner from an exact selected checkpoint.

        The live path never chooses an attempt, proficiency, or instructional
        response on the teacher's behalf. Item statistics are emitted only when
        one unambiguous producer attempt is present for a student/work pair.
        """

        grade_item_id = self._required(context, "grade_item")
        stored_item = load_current_grade_item_revision(
            context.root, context.class_id, grade_item_id
        )
        if stored_item is None:
            raise ReportMenuExecutionError(
                "The selected assessment no longer has a current revision."
            )
        checkpoint = self._checkpoint(context)
        request = checkpoint.snapshot.build_request
        evidence_by_student = {
            grade_request.target.student_id: tuple(
                item
                for item in (grade_request.work_evidence or ())
                if item.grade_item_id == grade_item_id
            )
            for grade_request in request.grade_requests
        }
        if not any(evidence_by_student.values()):
            raise ReportMenuExecutionError(
                "The current checkpoint does not contain the selected assessment."
            )

        projection_items: dict[tuple[str, str], tuple[EvidenceItem, ...]] = {}
        projection_sources: list[TeacherReportSourceReference] = []
        for grade_request in request.grade_requests:
            student_id = grade_request.target.student_id
            for evidence in evidence_by_student[student_id]:
                for reference in evidence.projection_snapshots:
                    key = (reference.publication_id, reference.cache_key)
                    if key in projection_items:
                        continue
                    authorized = self._load_benchmark_projection(
                        context,
                        reference.publication_id,
                        reference.cache_key,
                        reference.snapshot_digest,
                        tuple(
                            sorted(
                                candidate.target.student_id
                                for candidate in request.grade_requests
                                if any(
                                    reference in item.projection_snapshots
                                    for item in evidence_by_student[
                                        candidate.target.student_id
                                    ]
                                )
                            )
                        ),
                    )
                    projection_items[key] = authorized
                    projection_sources.append(
                        TeacherReportSourceReference(
                            "projection_snapshot",
                            f"{reference.publication_id}:{reference.cache_key}",
                            reference.snapshot_digest,
                        )
                    )

        roster = load_class_roster(context.root, context.class_id)
        roster_rows = {item.student_id: item for item in roster.students}
        observed: dict[str, tuple[EvidenceItem, ...]] = {}
        statuses: dict[str, set[str]] = {}
        for student_id, evidence_requests in evidence_by_student.items():
            student_items: dict[str, EvidenceItem] = {}
            statuses[student_id] = {item.status for item in evidence_requests}
            for evidence in evidence_requests:
                for reference in evidence.projection_snapshots:
                    for item in projection_items[
                        (reference.publication_id, reference.cache_key)
                    ]:
                        if (
                            item.subject is not None
                            and item.subject.student_id == student_id
                            and item.provenance.work == evidence.work
                        ):
                            prior = student_items.get(item.item_id)
                            if prior is not None and prior != item:
                                raise ReportMenuExecutionError(
                                    "Conflicting projected evidence identities were "
                                    "observed for the assessment."
                                )
                            student_items[item.item_id] = item
            observed[student_id] = tuple(
                student_items[key] for key in sorted(student_items)
            )

        standards = sorted(
            {
                standard
                for items in observed.values()
                for item in items
                for standard in item.target.standard_ids
            }
        )
        current_results: dict[
            tuple[str, str], StoredStandardProficiencyResult
        ] = {}
        scale_references: set[ProficiencyScaleReference] = set()
        source_references = list(projection_sources)
        for student_id in sorted(roster_rows):
            for standard_id in standards:
                current = load_current_standard_proficiency_result(
                    context.root,
                    context.class_id,
                    grade_item_id,
                    student_id,
                    standard_id,
                )
                if current is None:
                    continue
                current_results[(student_id, standard_id)] = current
                scale_references.add(current.snapshot.target_scale)
                source_references.append(
                    TeacherReportSourceReference(
                        "standard_proficiency_result",
                        (
                            f"{grade_item_id}:{student_id}:{standard_id}:"
                            f"{current.snapshot.result_revision}"
                        ),
                        current.result_sha256,
                    )
                )

        if len(scale_references) > 1:
            raise ReportMenuExecutionError(
                "The selected assessment uses more than one proficiency scale."
            )
        if scale_references:
            scale_reference = next(iter(scale_references))
            scale = load_proficiency_scale_revision(
                context.root,
                context.class_id,
                scale_reference.scale_id,
                scale_reference.scale_revision,
            )
            if scale.scale_sha256 != scale_reference.scale_sha256:
                raise ReportMenuExecutionError(
                    "The selected proficiency-scale revision could not be verified."
                )
        else:
            current_scales = []
            for scale_id in list_proficiency_scale_ids(
                context.root, context.class_id
            ):
                current_scale = load_current_proficiency_scale(
                    context.root, context.class_id, scale_id
                )
                if current_scale is not None:
                    current_scales.append(current_scale)
            candidates = tuple(current_scales)
            if len(candidates) != 1:
                raise ReportMenuExecutionError(
                    "Choose one current proficiency scale before running this report."
                )
            scale = candidates[0]
        source_references.extend(
            (
                TeacherReportSourceReference(
                    "grade_item_revision",
                    f"{grade_item_id}:{stored_item.revision.grade_item_revision}",
                    stored_item.revision_sha256,
                ),
                TeacherReportSourceReference(
                    "reporting_snapshot",
                    checkpoint.snapshot.snapshot_id,
                    checkpoint.snapshot_sha256,
                ),
                TeacherReportSourceReference(
                    "proficiency_scale",
                    f"{scale.scale.scale_id}:{scale.scale.scale_revision}",
                    scale.scale_sha256,
                ),
            )
        )

        student_results: list[BenchmarkStudentResult] = []
        for student_id, roster_row in sorted(roster_rows.items()):
            items = observed.get(student_id, ())
            selected = {
                current.snapshot.outcome.proficiency_level_id
                for (result_student, _), current in current_results.items()
                if result_student == student_id
                and current.snapshot.outcome.status == "calculated"
                and current.snapshot.outcome.proficiency_level_id is not None
            }
            status_set = statuses.get(student_id, set())
            tested = bool(items)
            result_status: BenchmarkResultStatus
            if tested and "unavailable" in status_set:
                result_status = "invalid_unresolved"
            elif tested:
                result_status = "valid"
            elif "missing" in status_set:
                result_status = "missing_result"
            else:
                result_status = "not_assessed"
            native_scores = {
                f"{item.value.earned}/{item.value.possible}"
                for item in items
                if item.result_kind == "attempt_points"
                and isinstance(item.value, NativePointValue)
            }
            student_results.append(
                BenchmarkStudentResult(
                    student_id=student_id,
                    student_name=f"{roster_row.first_name} {roster_row.last_name}",
                    expected=bool(evidence_by_student.get(student_id)),
                    tested=tested,
                    result_status=result_status,
                    native_score=(
                        next(iter(native_scores))
                        if result_status == "valid" and len(native_scores) == 1
                        else None
                    ),
                    selected_proficiency=(
                        next(iter(selected))
                        if result_status == "valid" and len(selected) == 1
                        else None
                    ),
                )
            )

        standard_rows: list[BenchmarkStandardObservation] = []
        for standard_id in standards:
            assessed_students = sum(
                any(standard_id in item.target.standard_ids for item in items)
                for items in observed.values()
            )
            results = [
                current
                for (student_id, result_standard), current in current_results.items()
                if result_standard == standard_id and student_id in roster_rows
            ]
            calculated = [
                current
                for current in results
                if current.snapshot.outcome.status == "calculated"
            ]
            counts: dict[str, int] = {}
            for current in calculated:
                level_id = current.snapshot.outcome.proficiency_level_id
                if level_id is not None:
                    counts[level_id] = counts.get(level_id, 0) + 1
            summary = "; ".join(
                f"{level_id}={count}" for level_id, count in sorted(counts.items())
            ) or "No selected proficiency results"
            if len(results) != len(calculated):
                summary += f"; insufficient={len(results) - len(calculated)}"
            standard_rows.append(
                BenchmarkStandardObservation(
                    standard_id=standard_id,
                    assessed_students=assessed_students,
                    valid_results=len(calculated),
                    native_summary=summary,
                )
            )

        return compose_benchmark_analysis(
            class_id=context.class_id,
            target_period=AcademicPeriodRef(
                context.period.school_year, context.period.period_id
            ),
            calendar_revision=context.period.calendar_revision,
            assessment_id=grade_item_id,
            assessment_title=stored_item.revision.title,
            proficiency_levels=tuple(level.level_id for level in scale.scale.levels),
            students=tuple(student_results),
            standards=tuple(standard_rows),
            items=_benchmark_item_observations(observed),
            source_references=tuple(source_references),
            generated_at=generated_at,
        )

    def _load_benchmark_projection(
        self,
        context: _Context,
        publication_id: str,
        cache_key: str,
        snapshot_digest: str,
        student_ids: tuple[str, ...],
    ) -> tuple[EvidenceItem, ...]:
        dependencies = self.dependencies.diagnostics
        if (
            dependencies is None
            or dependencies.authorizer is None
            or dependencies.producer_registry_state != "available"
            or dependencies.producer_registry is None
        ):
            raise ReportMenuExecutionError(
                "Benchmark evidence requires configured publication authorization "
                "and an available producer registry."
            )
        try:
            authorized = load_authorized_projection_snapshot(
                context.root,
                publication_id,
                cache_key,
                authorizer=dependencies.authorizer,
                authorization_purpose_id="teacher_reporting",
                requested_student_ids=student_ids,
                producer_registry=dependencies.producer_registry,
                adapter_registry=dependencies.adapter_registry,
                distribution_version_resolver=(
                    dependencies.distribution_version_resolver
                ),
            )
        except ProjectionCacheError as error:
            raise ReportMenuExecutionError(
                "The protected assessment projection could not be reauthorized."
            ) from error
        if authorized.stored.snapshot_digest != snapshot_digest:
            raise ReportMenuExecutionError(
                "The protected assessment projection changed after checkpointing."
            )
        if not authorized.assessment.reusable_for_current_use:
            raise ReportMenuExecutionError(
                "The protected assessment projection is no longer current."
            )
        return authorized.stored.snapshot.inventory.items

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


@dataclass(slots=True)
class _BenchmarkItemCounts:
    correct: int = 0
    incorrect: int = 0
    blank: int = 0
    ambiguous: int = 0
    standards: set[str] = field(default_factory=set)


def _benchmark_item_observations(
    observed: dict[str, tuple[EvidenceItem, ...]],
) -> tuple[BenchmarkItemObservation, ...]:
    """Aggregate only unambiguous single-attempt question evidence.

    A student/work with multiple observed attempts is excluded rather than
    silently choosing an attempt. Blank and ambiguous response states remain
    outside the correct/incorrect denominator.
    """

    totals: dict[str, _BenchmarkItemCounts] = {}
    for items in observed.values():
        by_work: dict[ModuleWorkRef, list[EvidenceItem]] = {}
        for item in items:
            if item.target.target_kind == "question":
                by_work.setdefault(item.provenance.work, []).append(item)
        for work, work_items in by_work.items():
            attempts = {
                item.target.parent_target.target_id
                for item in work_items
                if item.target.parent_target is not None
                and item.target.parent_target.target_kind == "attempt"
            }
            if len(attempts) != 1:
                continue
            question_ids = {
                item.target.target_id
                for item in work_items
                if item.target.target_id is not None
            }
            for question_id in sorted(question_ids):
                question_items = tuple(
                    item
                    for item in work_items
                    if item.target.target_id == question_id
                )
                correctness = tuple(
                    item.value.value
                    for item in question_items
                    if item.result_kind == "question_correctness"
                    and isinstance(item.value, NativeScalarValue)
                    and type(item.value.value) is bool
                )
                states = tuple(
                    item.value.code
                    for item in question_items
                    if item.result_kind == "selected_response_state"
                    and isinstance(item.value, NativeStateValue)
                )
                # A duplicate/conflicting response is not a valid item response.
                if len(correctness) != 1 or len(set(states)) > 1:
                    response = "ambiguous"
                elif states and states[0] == "blank":
                    response = "blank"
                elif states:
                    response = "ambiguous"
                else:
                    response = "correct" if correctness[0] else "incorrect"
                display_id = f"{work.work_id} / {question_id}"
                row = totals.setdefault(display_id, _BenchmarkItemCounts())
                if response == "correct":
                    row.correct += 1
                elif response == "incorrect":
                    row.incorrect += 1
                elif response == "blank":
                    row.blank += 1
                else:
                    row.ambiguous += 1
                for item in question_items:
                    row.standards.update(item.target.standard_ids)
    return tuple(
        BenchmarkItemObservation(
            item_id=item_id,
            correct_responses=values.correct,
            incorrect_responses=values.incorrect,
            blank_responses=values.blank,
            ambiguous_responses=values.ambiguous,
            standard_ids=tuple(sorted(values.standards)),
        )
        for item_id, values in sorted(totals.items())
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
