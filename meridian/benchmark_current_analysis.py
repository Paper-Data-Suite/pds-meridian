"""Report 9: live, authorized assessment analysis without a ReportingSnapshot.

Boundaries: exact current Grade Item memberships and Core publication catalog;
no SIS changes, inferred attempt selection, or manufactured proficiency. Producer
manifests are read only after a teacher_reporting authorization decision. This
path does not persist a projection cache or alter a student's academic state.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from pds_core.academic_catalog import PublicationCatalogQuery
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.classes import load_class_roster

from meridian.benchmark_analysis import (
    BenchmarkItemObservation,
    BenchmarkResultStatus,
    BenchmarkStandardObservation,
    BenchmarkStudentResult,
    compose_benchmark_analysis,
)
from meridian.diagnostics import DiagnosticsDependencies
from meridian.evidence import (
    EvidenceItem,
    NativePointValue,
    NativeScaledValue,
    NativeStateValue,
)
from meridian.grade_item_membership_storage import (
    list_selected_included_grade_item_memberships,
)
from meridian.grade_item_storage import load_current_grade_item_revision
from meridian.ingestion import (
    PublicationDiscoveryRequest,
    discover_publication_candidates,
    prepare_publication_invocation,
)
from meridian.proficiency_mapping import ProficiencyScaleReference
from meridian.proficiency_mapping_storage import (
    list_proficiency_scale_ids,
    load_current_proficiency_scale,
    load_proficiency_scale_revision,
)
from meridian.standards_proficiency_storage import (
    load_current_standard_proficiency_result,
)
from meridian.teacher_report import (
    TeacherReportPreview,
    TeacherReportSourceReference,
)

ItemObserver = Callable[
    [dict[str, tuple[EvidenceItem, ...]]], tuple[BenchmarkItemObservation, ...]
]


class CurrentBenchmarkUnavailableError(RuntimeError):
    """Current assessment data could not safely support the selected report."""

    code = "benchmark.current_unavailable"


def _native_result(item: EvidenceItem) -> bool:
    if item.result_kind == "attempt_points":
        return isinstance(item.value, NativePointValue)
    return item.result_kind in {
        "overall_standard_rating",
        "standard_observation_rating",
        "standard_backed_score",
        "local_score",
    } and isinstance(item.value, NativeScaledValue)


def _student_results(
    students: tuple[tuple[str, str], ...],
    observed: dict[str, tuple[EvidenceItem, ...]],
    selected_levels: dict[str, set[str]],
) -> tuple[BenchmarkStudentResult, ...]:
    results: list[BenchmarkStudentResult] = []
    for student_id, name in students:
        evidence = observed.get(student_id, ())
        scored = any(_native_result(item) for item in evidence)
        unresolved = any(
            isinstance(item.value, NativeStateValue)
            and item.value.code in {"invalid", "unresolved", "ambiguous"}
            for item in evidence
        )
        missing = any(
            isinstance(item.value, NativeStateValue)
            and item.value.code in {"missing", "missing_result"}
            for item in evidence
        )
        status: BenchmarkResultStatus
        if not evidence:
            status = "not_assessed"
        elif scored:
            status = "valid"
        elif unresolved:
            status = "invalid_unresolved"
        elif missing:
            status = "missing_result"
        else:
            status = "insufficient_evidence"
        attempts = {
            item.target.target_id: (
                f"{item.value.earned}/{item.value.possible}"
            )
            for item in evidence
            if item.result_kind == "attempt_points"
            and isinstance(item.value, NativePointValue)
        }
        # Multiple different attempts do not imply that the newest is selected.
        native_score = next(iter(attempts.values())) if len(attempts) == 1 else None
        levels = selected_levels.get(student_id, set())
        proficiency = next(iter(levels)) if len(levels) == 1 else None
        results.append(
            BenchmarkStudentResult(
                student_id=student_id,
                student_name=name,
                expected=True,
                tested=bool(evidence),
                result_status=status,
                native_score=native_score if status == "valid" else None,
                selected_proficiency=(
                    proficiency if status == "valid" else None
                ),
            )
        )
    return tuple(results)


def build_current_benchmark_analysis(
    workspace_root: str | Path,
    *,
    class_id: str,
    grade_item_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    generated_at: datetime,
    diagnostics: DiagnosticsDependencies | None,
    item_observer: ItemObserver,
) -> TeacherReportPreview:
    """Build a read-only report from current academic authorities, no checkpoint.

    Membership, current publication, runtime reader contract, and publication
    authorization must all hold. An absent current publication yields no observed
    result rather than a fabricated zero. This function makes no cache writes.
    """
    if (
        diagnostics is None
        or diagnostics.authorizer is None
        or diagnostics.producer_registry_state != "available"
        or diagnostics.producer_registry is None
    ):
        raise CurrentBenchmarkUnavailableError(
            "Set up evidence access before generating this benchmark report."
        )
    root = Path(workspace_root).resolve(strict=True)
    grade_item = load_current_grade_item_revision(root, class_id, grade_item_id)
    if grade_item is None or grade_item.revision.status != "active":
        raise CurrentBenchmarkUnavailableError(
            "This assessment is no longer an active Grade Item."
        )
    memberships = tuple(
        membership
        for membership in list_selected_included_grade_item_memberships(
            root, class_id, grade_item_id
        )
        if membership.decision.academic_period is not None
        and membership.decision.academic_period.period == target_period
        and membership.decision.academic_period.calendar_revision
        == calendar_revision
    )
    if not memberships:
        raise CurrentBenchmarkUnavailableError(
            "Include a published assessment in this Grade Item and marking "
            "period before generating Report 9. A ReportingSnapshot is not needed."
        )
    roster = load_class_roster(root, class_id)
    named_students = tuple(
        (row.student_id, f"{row.first_name} {row.last_name}")
        for row in sorted(roster.students, key=lambda row: row.student_id)
    )
    roster_ids = {student_id for student_id, _ in named_students}
    sources: list[TeacherReportSourceReference] = [
        TeacherReportSourceReference(
            "grade_item_revision",
            f"{grade_item_id}:{grade_item.revision.grade_item_revision}",
            grade_item.revision_sha256,
        )
    ]
    by_student: dict[str, dict[str, EvidenceItem]] = {}
    all_items: list[EvidenceItem] = []
    for membership in memberships:
        work = membership.decision.work_reference.work
        sources.append(
            TeacherReportSourceReference(
                "grade_item_membership",
                f"{grade_item_id}:{work.module_id}:{work.work_id}"
                f":{membership.decision.membership_revision}",
                membership.decision_sha256,
            )
        )
        candidates = discover_publication_candidates(
            root,
            PublicationDiscoveryRequest(
                PublicationCatalogQuery(
                    class_id=class_id,
                    module_id=work.module_id,
                    work_id=work.work_id,
                    publication_kind="academic_result_set",
                    state="current",
                    limit=256,
                )
            ),
        ).candidates
        if len(candidates) > 256:
            raise CurrentBenchmarkUnavailableError(
                "Too many current publications; narrow the assessment first."
            )
        for candidate in candidates:
            if candidate.catalog_publication.work != work:
                raise CurrentBenchmarkUnavailableError(
                    "The current publication no longer matches the selected work."
                )
            prepared = prepare_publication_invocation(
                root,
                candidate,
                producer_registry=diagnostics.producer_registry,
                adapter_registry=diagnostics.adapter_registry,
                authorizer=diagnostics.authorizer,
                authorization_purpose_id="teacher_reporting",
                requested_student_ids=(),
                distribution_version_resolver=(
                    diagnostics.distribution_version_resolver
                ),
            )
            referenced = prepared.canonical_context.referenced_registration
            if (
                referenced is None
                or referenced.registration_revision
                != membership.decision.work_reference.registration_revision
            ):
                raise CurrentBenchmarkUnavailableError(
                    "The assessment membership references an older work revision. "
                    "Review its membership before running Report 9."
                )
            published = prepared.canonical_context.publication
            sources.append(
                TeacherReportSourceReference(
                    "publication", published.publication_id,
                    published.manifest_digest,
                )
            )
            inventory = diagnostics.adapter_registry.invoke(
                prepared.projection_request,
                diagnostics.distribution_version_resolver,
                producer_profile=prepared.producer_profile,
            )
            for item in inventory.items:
                all_items.append(item)
                subject = item.subject
                if subject is None:
                    # Shared Concord group results must not be assigned to
                    # individual students without an explicit supported link.
                    continue
                if subject.student_id not in roster_ids:
                    raise CurrentBenchmarkUnavailableError(
                        "Published evidence names a student absent from the "
                        "Core roster."
                    )
                per_student = by_student.setdefault(subject.student_id, {})
                previous = per_student.get(item.item_id)
                if previous is not None and previous != item:
                    raise CurrentBenchmarkUnavailableError(
                        "Conflicting published evidence identities were observed."
                    )
                per_student[item.item_id] = item
    observed = {
        student_id: tuple(items[key] for key in sorted(items))
        for student_id, items in by_student.items()
    }
    standards = tuple(sorted({
        standard_id for item in all_items
        for standard_id in item.target.standard_ids
    }))
    level_by_student: dict[str, set[str]] = {}
    scale_refs: set[ProficiencyScaleReference] = set()
    standard_observations: list[BenchmarkStandardObservation] = []
    for standard_id in standards:
        assessed = {
            student_id for student_id, items in observed.items()
            if any(standard_id in item.target.standard_ids for item in items)
        }
        counts: dict[str, int] = {}
        calculated_count = 0
        for student_id in roster_ids:
            result = load_current_standard_proficiency_result(
                root, class_id, grade_item_id, student_id, standard_id
            )
            if result is None:
                continue
            scale_refs.add(result.snapshot.target_scale)
            sources.append(
                TeacherReportSourceReference(
                    "standard_proficiency_result",
                    f"{grade_item_id}:{student_id}:{standard_id}:"
                    f"{result.snapshot.result_revision}",
                    result.result_sha256,
                )
            )
            outcome = result.snapshot.outcome
            if outcome.status == "calculated" and outcome.proficiency_level_id:
                level = outcome.proficiency_level_id
                level_by_student.setdefault(student_id, set()).add(level)
                if student_id in assessed:
                    counts[level] = counts.get(level, 0) + 1
                    calculated_count += 1
        summary = "; ".join(
            f"{level}={count}" for level, count in sorted(counts.items())
        ) or "No selected proficiency results"
        standard_observations.append(
            BenchmarkStandardObservation(
                standard_id=standard_id,
                assessed_students=len(assessed),
                valid_results=calculated_count,
                native_summary=summary,
            )
        )
    if len(scale_refs) > 1:
        raise CurrentBenchmarkUnavailableError(
            "The selected Grade Item uses different proficiency scales. "
            "Reconcile the scales before generating this report."
        )
    if scale_refs:
        scale_ref = next(iter(scale_refs))
        scale = load_proficiency_scale_revision(
            root, class_id, scale_ref.scale_id, scale_ref.scale_revision
        )
        if scale.scale_sha256 != scale_ref.scale_sha256:
            raise CurrentBenchmarkUnavailableError(
                "The configured proficiency-scale revision changed."
            )
    else:
        available = tuple(
            existing for scale_id in list_proficiency_scale_ids(root, class_id)
            if (existing := load_current_proficiency_scale(
                root, class_id, scale_id
            )) is not None
        )
        if len(available) != 1:
            raise CurrentBenchmarkUnavailableError(
                "Choose one current proficiency scale for the class first."
            )
        scale = available[0]
    sources.append(
        TeacherReportSourceReference(
            "proficiency_scale",
            f"{scale.scale.scale_id}:{scale.scale.scale_revision}",
            scale.scale_sha256,
        )
    )
    return compose_benchmark_analysis(
        class_id=class_id,
        target_period=target_period,
        calendar_revision=calendar_revision,
        assessment_id=grade_item_id,
        assessment_title=grade_item.revision.title,
        proficiency_levels=tuple(level.level_id for level in scale.scale.levels),
        students=_student_results(named_students, observed, level_by_student),
        standards=tuple(standard_observations),
        items=item_observer(observed),
        source_references=tuple(sources),
        generated_at=generated_at,
    )


__all__ = (
    "CurrentBenchmarkUnavailableError",
    "build_current_benchmark_analysis",
)
