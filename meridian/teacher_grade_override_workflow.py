"""Exact source binding and active teacher Grade override authoring workflow.

This module is the bounded family-dispatch boundary for Issue #53. It resolves
one exact selected conventional, standards-based, or hybrid Grade result,
assesses that result with the existing family-specific freshness contract, and
authors a new immutable active override against that exact selected source.

The workflow never mutates a base Grade result and never treats newest/highest
result history as selected authority. Effective-Grade precedence remains a
separate layer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade import (
    ConventionalGradeValidationError,
    assess_conventional_grade_result_freshness,
)
from meridian.conventional_grade_assembly import (
    ConventionalGradeAssemblyError,
    ConventionalGradeWorkEvidenceSpec,
    assemble_conventional_grade_calculation,
)
from meridian.conventional_grade_storage import (
    ConventionalGradeStorageError,
    StoredConventionalGradeResult,
    load_conventional_grade_result_revision,
    load_current_conventional_grade_result,
)
from meridian.grade_policy import (
    GradeCalculationFamily,
    GradePolicyActor,
    GradePolicyValidationError,
)
from meridian.hybrid_grade_assembly import (
    HybridGradeAssemblyError,
    assemble_hybrid_grade_calculation,
)
from meridian.hybrid_grade_result import (
    HybridGradeResultValidationError,
    assess_hybrid_grade_result_freshness,
)
from meridian.hybrid_grade_storage import (
    HybridGradeStorageError,
    StoredHybridGradeResult,
    load_current_hybrid_grade_result,
    load_hybrid_grade_result_revision,
)
from meridian.standards_grade_assembly import (
    StandardsGradeAssemblyError,
    assemble_standards_grade_calculation,
)
from meridian.standards_grade_result import (
    StandardsGradeResultValidationError,
    assess_standards_grade_result_freshness,
)
from meridian.standards_grade_storage import (
    StandardsGradeStorageError,
    StoredStandardsGradeResult,
    load_current_standards_grade_result,
    load_standards_grade_result_revision,
)
from meridian.teacher_grade_override import (
    TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
    TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecision,
    TeacherGradeOverrideReference,
    TeacherGradeOverrideValidationError,
    teacher_grade_override_decision_to_json_bytes,
    teacher_grade_override_reference,
    validate_teacher_grade_override_transition,
)
from meridian.teacher_grade_override_storage import (
    TeacherGradeOverrideStorageError,
    TeacherGradeOverrideWriteDisposition,
    get_current_teacher_grade_override_reference,
    list_teacher_grade_override_revisions,
    load_teacher_grade_override_revision,
    write_teacher_grade_override_revision,
)

TeacherGradeOverrideBaseStatus: TypeAlias = Literal[
    "calculated",
    "blocked",
    "insufficient",
]
TeacherGradeOverrideFreshnessStatus: TypeAlias = Literal["current", "stale"]
TeacherGradeOverrideApplicabilityStatus: TypeAlias = Literal[
    "applicable",
    "withdrawn",
    "source_mismatch",
    "source_stale",
]
TeacherGradeOverrideApplicabilityReason: TypeAlias = Literal[
    "selected_override_withdrawn",
    "source_result_mismatch",
    "source_result_stale",
]

_BASE_STATUSES = frozenset({"calculated", "blocked", "insufficient"})
_FRESHNESS_STATUSES = frozenset({"current", "stale"})
_APPLICABILITY_REASONS = frozenset(
    {
        "selected_override_withdrawn",
        "source_result_mismatch",
        "source_result_stale",
    }
)


class TeacherGradeOverrideWorkflowError(RuntimeError):
    """Base error for exact teacher Grade override workflow operations."""

    code = "teacher_workflow.grade_override.error"


class TeacherGradeOverrideWorkflowScopeError(
    TeacherGradeOverrideWorkflowError, ValueError
):
    """Raised when requested override workflow scope is invalid."""

    code = "teacher_workflow.grade_override.scope_invalid"


class TeacherGradeOverrideSourceUnavailableError(TeacherGradeOverrideWorkflowError):
    """Raised when the requested family has no explicit selected Grade result."""

    code = "teacher_workflow.grade_override.source_unavailable"


class TeacherGradeOverrideSourceIntegrityError(TeacherGradeOverrideWorkflowError):
    """Raised when exact source Grade-result storage cannot be trusted."""

    code = "teacher_workflow.grade_override.source_integrity_invalid"


class TeacherGradeOverrideSourceCurrentnessError(
    TeacherGradeOverrideWorkflowError
):
    """Raised when the existing family freshness basis cannot be established."""

    code = "teacher_workflow.grade_override.source_currentness_unavailable"


class TeacherGradeOverrideAuthoringStaleError(TeacherGradeOverrideWorkflowError):
    """Raised when reviewed source/history authority changed before commit."""

    code = "teacher_workflow.grade_override.authoring_stale"


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideSourceResult:
    """One exact verified immutable base Grade result needed by #53."""

    source_result: GradeOverrideSourceResultReference
    source_status: TeacherGradeOverrideBaseStatus
    base_grade: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.source_result, GradeOverrideSourceResultReference):
            raise TeacherGradeOverrideWorkflowScopeError(
                "source_result must be a GradeOverrideSourceResultReference."
            )
        if self.source_status not in _BASE_STATUSES:
            raise TeacherGradeOverrideWorkflowScopeError(
                "source_status must be calculated, blocked, or insufficient."
            )
        grade = self.base_grade
        if self.source_status == "calculated":
            if not isinstance(grade, Decimal) or not grade.is_finite():
                raise TeacherGradeOverrideWorkflowScopeError(
                    "calculated source result requires an exact finite base_grade."
                )
        elif grade is not None:
            raise TeacherGradeOverrideWorkflowScopeError(
                "blocked/insufficient source result must not carry base_grade."
            )


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideSelectedSource:
    """Exact selected source plus its existing family-specific freshness."""

    source: TeacherGradeOverrideSourceResult
    freshness_status: TeacherGradeOverrideFreshnessStatus
    freshness_reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source, TeacherGradeOverrideSourceResult):
            raise TeacherGradeOverrideWorkflowScopeError(
                "source must be TeacherGradeOverrideSourceResult."
            )
        if self.freshness_status not in _FRESHNESS_STATUSES:
            raise TeacherGradeOverrideWorkflowScopeError(
                "freshness_status must be current or stale."
            )
        try:
            reasons = tuple(self.freshness_reasons)
        except TypeError as error:
            raise TeacherGradeOverrideWorkflowScopeError(
                "freshness_reasons must be iterable."
            ) from error
        if any(not isinstance(reason, str) or not reason for reason in reasons):
            raise TeacherGradeOverrideWorkflowScopeError(
                "freshness_reasons must contain nonblank strings."
            )
        if len(set(reasons)) != len(reasons):
            raise TeacherGradeOverrideWorkflowScopeError(
                "freshness_reasons must not contain duplicates."
            )
        if self.freshness_status == "current" and reasons:
            raise TeacherGradeOverrideWorkflowScopeError(
                "current source must not carry freshness_reasons."
            )
        if self.freshness_status == "stale" and not reasons:
            raise TeacherGradeOverrideWorkflowScopeError(
                "stale source requires freshness_reasons."
            )
        object.__setattr__(self, "freshness_reasons", reasons)

    @property
    def source_result(self) -> GradeOverrideSourceResultReference:
        return self.source.source_result

    @property
    def source_status(self) -> TeacherGradeOverrideBaseStatus:
        return self.source.source_status

    @property
    def base_grade(self) -> Decimal | None:
        return self.source.base_grade


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideApplicability:
    """Pure non-floating applicability assessment for one selected override."""

    status: TeacherGradeOverrideApplicabilityStatus
    reasons: tuple[TeacherGradeOverrideApplicabilityReason, ...]

    def __post_init__(self) -> None:
        if self.status not in {
            "applicable",
            "withdrawn",
            "source_mismatch",
            "source_stale",
        }:
            raise TeacherGradeOverrideWorkflowScopeError(
                "unsupported override applicability status."
            )
        reasons = tuple(self.reasons)
        if any(reason not in _APPLICABILITY_REASONS for reason in reasons):
            raise TeacherGradeOverrideWorkflowScopeError(
                "unsupported override applicability reason."
            )
        if len(set(reasons)) != len(reasons):
            raise TeacherGradeOverrideWorkflowScopeError(
                "override applicability reasons must not contain duplicates."
            )
        expected: dict[
            TeacherGradeOverrideApplicabilityStatus,
            tuple[TeacherGradeOverrideApplicabilityReason, ...],
        ] = {
            "applicable": (),
            "withdrawn": ("selected_override_withdrawn",),
            "source_mismatch": ("source_result_mismatch",),
            "source_stale": ("source_result_stale",),
        }
        if reasons != expected[self.status]:
            raise TeacherGradeOverrideWorkflowScopeError(
                "override applicability reasons do not match status."
            )
        object.__setattr__(self, "reasons", reasons)


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideAuthoringPreview:
    """Exact reviewed basis for one immutable active override revision."""

    source: TeacherGradeOverrideSelectedSource
    history_before: tuple[int, ...]
    latest_override_sha256_before: str | None
    candidate: TeacherGradeOverrideDecision
    candidate_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.source, TeacherGradeOverrideSelectedSource):
            raise TeacherGradeOverrideWorkflowScopeError(
                "source must be TeacherGradeOverrideSelectedSource."
            )
        history = tuple(self.history_before)
        if history != tuple(range(1, self.candidate.override_revision)):
            raise TeacherGradeOverrideWorkflowScopeError(
                "history_before must exactly precede candidate override revision."
            )
        if bool(history) != bool(self.latest_override_sha256_before):
            raise TeacherGradeOverrideWorkflowScopeError(
                "latest override digest presence must match history presence."
            )
        if self.candidate.decision != "override":
            raise TeacherGradeOverrideWorkflowScopeError(
                "active override authoring preview requires decision=override."
            )
        if self.candidate.source_result != self.source.source_result:
            raise TeacherGradeOverrideWorkflowScopeError(
                "candidate must bind the exact reviewed selected source result."
            )
        expected_digest = hashlib.sha256(
            teacher_grade_override_decision_to_json_bytes(self.candidate)
        ).hexdigest()
        if self.candidate_sha256 != expected_digest:
            raise TeacherGradeOverrideWorkflowScopeError(
                "candidate_sha256 must bind exact candidate canonical bytes."
            )
        object.__setattr__(self, "history_before", history)


@dataclass(frozen=True, slots=True)
class TeacherGradeOverrideAuthoringResult:
    """Result of committing one exact previewed active override revision."""

    preview: TeacherGradeOverrideAuthoringPreview
    write_disposition: TeacherGradeOverrideWriteDisposition
    stored_reference: TeacherGradeOverrideReference
    selected_override_after: TeacherGradeOverrideReference | None

    def __post_init__(self) -> None:
        if not isinstance(self.preview, TeacherGradeOverrideAuthoringPreview):
            raise TeacherGradeOverrideWorkflowScopeError(
                "preview must be TeacherGradeOverrideAuthoringPreview."
            )
        if self.write_disposition not in {"created", "existing"}:
            raise TeacherGradeOverrideWorkflowScopeError(
                "write_disposition must be created or existing."
            )
        expected = teacher_grade_override_reference(self.preview.candidate)
        if self.stored_reference != expected:
            raise TeacherGradeOverrideWorkflowScopeError(
                "stored_reference must identify the exact previewed candidate."
            )


def load_teacher_grade_override_source_result(
    workspace_root: str | Path,
    source_result: GradeOverrideSourceResultReference,
) -> TeacherGradeOverrideSourceResult:
    """Load one exact family-tagged immutable Grade result by revision+digest."""

    if not isinstance(source_result, GradeOverrideSourceResultReference):
        raise TeacherGradeOverrideWorkflowScopeError(
            "source_result must be a GradeOverrideSourceResultReference."
        )
    reference = source_result.reference
    period = AcademicPeriodRef(reference.school_year, reference.period_id)
    try:
        if source_result.family == "conventional":
            conventional_stored = load_conventional_grade_result_revision(
                workspace_root,
                reference.class_id,
                reference.student_id,
                period,
                reference.calendar_revision,
                reference.result_revision,
            )
            exact = _conventional_source(conventional_stored)
        elif source_result.family == "standards_based":
            standards_stored = load_standards_grade_result_revision(
                workspace_root,
                reference.class_id,
                reference.student_id,
                period,
                reference.calendar_revision,
                reference.result_revision,
            )
            exact = _standards_source(standards_stored)
        elif source_result.family == "hybrid":
            hybrid_stored = load_hybrid_grade_result_revision(
                workspace_root,
                reference.class_id,
                reference.student_id,
                period,
                reference.calendar_revision,
                reference.result_revision,
            )
            exact = _hybrid_source(hybrid_stored)
        else:
            raise TeacherGradeOverrideWorkflowScopeError(
                "unsupported source Grade-result family."
            )
    except (
        ConventionalGradeStorageError,
        StandardsGradeStorageError,
        HybridGradeStorageError,
    ) as error:
        raise TeacherGradeOverrideSourceIntegrityError(
            f"Exact source Grade result could not be verified: {error}"
        ) from error
    if exact.source_result != source_result:
        raise TeacherGradeOverrideSourceIntegrityError(
            "Exact source Grade result digest/scope does not match reference."
        )
    return exact


def load_selected_teacher_grade_override_source(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
) -> TeacherGradeOverrideSourceResult:
    """Load only the explicit selected source result for one exact Grade family."""

    try:
        if calculation_family == "conventional":
            conventional_stored = load_current_conventional_grade_result(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
            )
            if conventional_stored is None:
                raise TeacherGradeOverrideSourceUnavailableError(
                    "Conventional Grade result has no explicit current selection."
                )
            return _conventional_source(conventional_stored)
        if calculation_family == "standards_based":
            standards_stored = load_current_standards_grade_result(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
            )
            if standards_stored is None:
                raise TeacherGradeOverrideSourceUnavailableError(
                    "Standards Grade result has no explicit current selection."
                )
            return _standards_source(standards_stored)
        if calculation_family == "hybrid":
            hybrid_stored = load_current_hybrid_grade_result(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
            )
            if hybrid_stored is None:
                raise TeacherGradeOverrideSourceUnavailableError(
                    "Hybrid Grade result has no explicit current selection."
                )
            return _hybrid_source(hybrid_stored)
    except TeacherGradeOverrideSourceUnavailableError:
        raise
    except (
        ConventionalGradeStorageError,
        StandardsGradeStorageError,
        HybridGradeStorageError,
    ) as error:
        raise TeacherGradeOverrideSourceIntegrityError(
            f"Selected source Grade result could not be verified: {error}"
        ) from error
    raise TeacherGradeOverrideWorkflowScopeError(
        "calculation_family must be conventional, standards_based, or hybrid."
    )


def resolve_selected_teacher_grade_override_source(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
    *,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None = None,
) -> TeacherGradeOverrideSelectedSource:
    """Resolve selected source and assess it with #50/#51/#52 freshness rules."""

    source = load_selected_teacher_grade_override_source(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        calculation_family,
    )
    try:
        if calculation_family == "conventional":
            if work_evidence is None:
                raise TeacherGradeOverrideWorkflowScopeError(
                    "conventional source freshness requires explicit work_evidence."
                )
            conventional_assembly = assemble_conventional_grade_calculation(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
                work_evidence,
            )
            conventional_stored = load_current_conventional_grade_result(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
            )
            if conventional_stored is None:
                raise TeacherGradeOverrideAuthoringStaleError(
                    "Selected conventional source changed during freshness assessment."
                )
            if (
                _conventional_source(conventional_stored).source_result
                != source.source_result
            ):
                raise TeacherGradeOverrideAuthoringStaleError(
                    "Selected conventional source changed during freshness assessment."
                )
            conventional_freshness = assess_conventional_grade_result_freshness(
                conventional_stored.snapshot,
                conventional_assembly.inputs,
            )
            return TeacherGradeOverrideSelectedSource(
                source=source,
                freshness_status=conventional_freshness.status,
                freshness_reasons=tuple(conventional_freshness.reasons),
            )

        if calculation_family == "standards_based":
            if work_evidence:
                raise TeacherGradeOverrideWorkflowScopeError(
                    "standards-based source freshness does not accept work_evidence."
                )
            standards_assembly = assemble_standards_grade_calculation(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
            )
            standards_stored = load_current_standards_grade_result(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
            )
            if standards_stored is None:
                raise TeacherGradeOverrideAuthoringStaleError(
                    "Selected standards source changed during freshness assessment."
                )
            if (
                _standards_source(standards_stored).source_result
                != source.source_result
            ):
                raise TeacherGradeOverrideAuthoringStaleError(
                    "Selected standards source changed during freshness assessment."
                )
            standards_freshness = assess_standards_grade_result_freshness(
                standards_stored.snapshot,
                standards_assembly.inputs,
            )
            return TeacherGradeOverrideSelectedSource(
                source=source,
                freshness_status=standards_freshness.status,
                freshness_reasons=tuple(standards_freshness.reasons),
            )

        if calculation_family == "hybrid":
            if work_evidence is None:
                raise TeacherGradeOverrideWorkflowScopeError(
                    "hybrid source freshness requires explicit work_evidence."
                )
            hybrid_assembly = assemble_hybrid_grade_calculation(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
                work_evidence,
            )
            hybrid_stored = load_current_hybrid_grade_result(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
            )
            if hybrid_stored is None:
                raise TeacherGradeOverrideAuthoringStaleError(
                    "Selected hybrid source changed during freshness assessment."
                )
            if _hybrid_source(hybrid_stored).source_result != source.source_result:
                raise TeacherGradeOverrideAuthoringStaleError(
                    "Selected hybrid source changed during freshness assessment."
                )
            hybrid_freshness = assess_hybrid_grade_result_freshness(
                hybrid_stored.snapshot,
                hybrid_assembly.inputs,
            )
            return TeacherGradeOverrideSelectedSource(
                source=source,
                freshness_status=hybrid_freshness.status,
                freshness_reasons=tuple(hybrid_freshness.reasons),
            )

        raise TeacherGradeOverrideWorkflowScopeError(
            "unsupported source Grade-result family."
        )
    except TeacherGradeOverrideWorkflowError:
        raise
    except (
        ConventionalGradeAssemblyError,
        StandardsGradeAssemblyError,
        HybridGradeAssemblyError,
        ConventionalGradeValidationError,
        StandardsGradeResultValidationError,
        HybridGradeResultValidationError,
    ) as error:
        raise TeacherGradeOverrideSourceCurrentnessError(
            f"Current source Grade basis could not be assessed: {error}"
        ) from error
    except (
        ConventionalGradeStorageError,
        StandardsGradeStorageError,
        HybridGradeStorageError,
    ) as error:
        raise TeacherGradeOverrideSourceIntegrityError(
            f"Selected source changed or became invalid: {error}"
        ) from error


def assess_teacher_grade_override_applicability(
    selected_source: TeacherGradeOverrideSelectedSource,
    selected_override: TeacherGradeOverrideDecision,
) -> TeacherGradeOverrideApplicability:
    """Purely assess exact-reference applicability without mutating either side."""

    if not isinstance(selected_source, TeacherGradeOverrideSelectedSource):
        raise TeacherGradeOverrideWorkflowScopeError(
            "selected_source must be TeacherGradeOverrideSelectedSource."
        )
    if not isinstance(selected_override, TeacherGradeOverrideDecision):
        raise TeacherGradeOverrideWorkflowScopeError(
            "selected_override must be TeacherGradeOverrideDecision."
        )
    if selected_override.decision == "withdraw":
        return TeacherGradeOverrideApplicability(
            "withdrawn",
            ("selected_override_withdrawn",),
        )
    if selected_override.source_result != selected_source.source_result:
        return TeacherGradeOverrideApplicability(
            "source_mismatch",
            ("source_result_mismatch",),
        )
    if selected_source.freshness_status == "stale":
        return TeacherGradeOverrideApplicability(
            "source_stale",
            ("source_result_stale",),
        )
    return TeacherGradeOverrideApplicability("applicable", ())


def preview_teacher_grade_override_authoring(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
    *,
    replacement_grade: Decimal,
    actor_id: str,
    rationale: str,
    decided_at: datetime,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None = None,
) -> TeacherGradeOverrideAuthoringPreview:
    """Preview one new active override bound to the exact selected source result."""

    source = resolve_selected_teacher_grade_override_source(
        workspace_root,
        class_id,
        student_id,
        target_period,
        calendar_revision,
        calculation_family,
        work_evidence=work_evidence,
    )
    try:
        history = list_teacher_grade_override_revisions(
            workspace_root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
            calculation_family,
        )
        latest = (
            None
            if not history
            else load_teacher_grade_override_revision(
                workspace_root,
                class_id,
                student_id,
                target_period,
                calendar_revision,
                calculation_family,
                history[-1],
            )
        )
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Override history could not be verified: {error}"
        ) from error

    try:
        actor = GradePolicyActor("teacher", actor_id)
        revision = len(history) + 1
        candidate = TeacherGradeOverrideDecision(
            schema_version=TEACHER_GRADE_OVERRIDE_SCHEMA_VERSION,
            record_type=TEACHER_GRADE_OVERRIDE_RECORD_TYPE,
            class_id=class_id,
            student_id=student_id,
            target_period=target_period,
            calendar_revision=calendar_revision,
            calculation_family=calculation_family,
            override_revision=revision,
            supersedes_revision=None if revision == 1 else revision - 1,
            decision="override",
            source_result=source.source_result,
            replacement_grade=replacement_grade,
            withdrawn_override_reference=None,
            actor=actor,
            rationale=rationale,
            decided_at=decided_at,
        )
    except (GradePolicyValidationError, TeacherGradeOverrideValidationError) as error:
        raise TeacherGradeOverrideWorkflowScopeError(str(error)) from error

    if latest is not None:
        try:
            validate_teacher_grade_override_transition(latest.decision, candidate)
        except TeacherGradeOverrideValidationError as error:
            raise TeacherGradeOverrideWorkflowScopeError(str(error)) from error

    content = teacher_grade_override_decision_to_json_bytes(candidate)
    return TeacherGradeOverrideAuthoringPreview(
        source=source,
        history_before=history,
        latest_override_sha256_before=(
            None if latest is None else latest.override_sha256
        ),
        candidate=candidate,
        candidate_sha256=hashlib.sha256(content).hexdigest(),
    )


def commit_teacher_grade_override_authoring_preview(
    workspace_root: str | Path,
    preview: TeacherGradeOverrideAuthoringPreview,
) -> TeacherGradeOverrideAuthoringResult:
    """Commit exactly one reviewed active override without selecting it."""

    if not isinstance(preview, TeacherGradeOverrideAuthoringPreview):
        raise TeacherGradeOverrideWorkflowScopeError(
            "preview must be TeacherGradeOverrideAuthoringPreview."
        )
    candidate = preview.candidate
    try:
        history = list_teacher_grade_override_revisions(
            workspace_root,
            candidate.class_id,
            candidate.student_id,
            candidate.target_period,
            candidate.calendar_revision,
            candidate.calculation_family,
        )
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Override history could not be revalidated: {error}"
        ) from error

    replay_history = preview.history_before + (candidate.override_revision,)
    exact_replay = history == replay_history
    if history != preview.history_before and not exact_replay:
        raise TeacherGradeOverrideAuthoringStaleError(
            "Override revision history changed after authoring preview."
        )

    if exact_replay:
        try:
            existing = load_teacher_grade_override_revision(
                workspace_root,
                candidate.class_id,
                candidate.student_id,
                candidate.target_period,
                candidate.calendar_revision,
                candidate.calculation_family,
                candidate.override_revision,
            )
        except TeacherGradeOverrideStorageError as error:
            raise TeacherGradeOverrideWorkflowError(
                f"Previewed override replay could not be verified: {error}"
            ) from error
        if (
            existing.decision != candidate
            or existing.override_sha256 != preview.candidate_sha256
        ):
            raise TeacherGradeOverrideAuthoringStaleError(
                "Existing candidate revision differs from authoring preview."
            )
    elif preview.history_before:
        try:
            latest = load_teacher_grade_override_revision(
                workspace_root,
                candidate.class_id,
                candidate.student_id,
                candidate.target_period,
                candidate.calendar_revision,
                candidate.calculation_family,
                preview.history_before[-1],
            )
        except TeacherGradeOverrideStorageError as error:
            raise TeacherGradeOverrideWorkflowError(
                f"Latest override revision could not be revalidated: {error}"
            ) from error
        if latest.override_sha256 != preview.latest_override_sha256_before:
            raise TeacherGradeOverrideAuthoringStaleError(
                "Latest override revision changed after authoring preview."
            )

    expected_source = preview.source.source_result
    if not exact_replay:
        _require_selected_source_reference(
            workspace_root,
            expected_source,
            message="Selected source changed after authoring preview.",
        )

    def precommit_guard() -> None:
        _require_selected_source_reference(
            workspace_root,
            expected_source,
            message="Selected source changed before override commit.",
        )

    try:
        written = write_teacher_grade_override_revision(
            workspace_root,
            candidate,
            precommit_guard=None if exact_replay else precommit_guard,
        )
    except TeacherGradeOverrideAuthoringStaleError:
        raise
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Override revision could not be persisted: {error}"
        ) from error

    if written.stored.decision != candidate:
        raise TeacherGradeOverrideWorkflowError(
            "Persisted override decision differs from authoring preview."
        )
    if written.stored.override_sha256 != preview.candidate_sha256:
        raise TeacherGradeOverrideWorkflowError(
            "Persisted override digest differs from authoring preview."
        )

    _require_selected_source_reference(
        workspace_root,
        expected_source,
        message="Selected source changed while override commit completed.",
    )

    try:
        selected_after = get_current_teacher_grade_override_reference(
            workspace_root,
            candidate.class_id,
            candidate.student_id,
            candidate.target_period,
            candidate.calendar_revision,
            candidate.calculation_family,
        )
    except TeacherGradeOverrideStorageError as error:
        raise TeacherGradeOverrideWorkflowError(
            f"Override current selection could not be read: {error}"
        ) from error
    return TeacherGradeOverrideAuthoringResult(
        preview=preview,
        write_disposition=written.disposition,
        stored_reference=written.stored.reference,
        selected_override_after=selected_after,
    )


def _require_selected_source_reference(
    workspace_root: str | Path,
    expected: GradeOverrideSourceResultReference,
    *,
    message: str,
) -> None:
    reference = expected.reference
    period = AcademicPeriodRef(reference.school_year, reference.period_id)
    try:
        current = load_selected_teacher_grade_override_source(
            workspace_root,
            reference.class_id,
            reference.student_id,
            period,
            reference.calendar_revision,
            expected.family,
        )
    except TeacherGradeOverrideSourceUnavailableError as error:
        raise TeacherGradeOverrideAuthoringStaleError(message) from error
    if current.source_result != expected:
        raise TeacherGradeOverrideAuthoringStaleError(message)


def _conventional_source(
    stored: StoredConventionalGradeResult,
) -> TeacherGradeOverrideSourceResult:
    reference = GradeOverrideSourceResultReference(
        "conventional",
        stored.reference,
    )
    return TeacherGradeOverrideSourceResult(
        source_result=reference,
        source_status=stored.snapshot.outcome.status,
        base_grade=stored.snapshot.outcome.rounded_grade,
    )


def _standards_source(
    stored: StoredStandardsGradeResult,
) -> TeacherGradeOverrideSourceResult:
    reference = GradeOverrideSourceResultReference(
        "standards_based",
        stored.reference,
    )
    return TeacherGradeOverrideSourceResult(
        source_result=reference,
        source_status=stored.snapshot.outcome.status,
        base_grade=stored.snapshot.outcome.rounded_grade,
    )


def _hybrid_source(
    stored: StoredHybridGradeResult,
) -> TeacherGradeOverrideSourceResult:
    reference = GradeOverrideSourceResultReference(
        "hybrid",
        stored.reference,
    )
    return TeacherGradeOverrideSourceResult(
        source_result=reference,
        source_status=stored.snapshot.outcome.status,
        base_grade=stored.snapshot.outcome.rounded_grade,
    )


__all__ = [
    "TeacherGradeOverrideApplicability",
    "TeacherGradeOverrideApplicabilityReason",
    "TeacherGradeOverrideApplicabilityStatus",
    "TeacherGradeOverrideAuthoringPreview",
    "TeacherGradeOverrideAuthoringResult",
    "TeacherGradeOverrideAuthoringStaleError",
    "TeacherGradeOverrideBaseStatus",
    "TeacherGradeOverrideFreshnessStatus",
    "TeacherGradeOverrideSelectedSource",
    "TeacherGradeOverrideSourceCurrentnessError",
    "TeacherGradeOverrideSourceIntegrityError",
    "TeacherGradeOverrideSourceResult",
    "TeacherGradeOverrideSourceUnavailableError",
    "TeacherGradeOverrideWorkflowError",
    "TeacherGradeOverrideWorkflowScopeError",
    "assess_teacher_grade_override_applicability",
    "commit_teacher_grade_override_authoring_preview",
    "load_selected_teacher_grade_override_source",
    "load_teacher_grade_override_source_result",
    "preview_teacher_grade_override_authoring",
    "resolve_selected_teacher_grade_override_source",
]
