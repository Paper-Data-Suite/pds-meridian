"""Deterministic read-only effective Academic Period Grade resolution.

Issue #53 keeps immutable base Grade calculation, source freshness, and teacher
override authority separate. This module composes those exact existing contracts
without mutating any source or inferring authority from revision order, time, or
Grade value.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.academic_periods import AcademicPeriodRef

from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.grade_policy import GradeCalculationFamily
from meridian.teacher_grade_override import (
    GradeOverrideSourceResultReference,
    TeacherGradeOverrideDecision,
    TeacherGradeOverrideReference,
    teacher_grade_override_reference,
)
from meridian.teacher_grade_override_storage import (
    TeacherGradeOverrideStorageError,
    load_current_teacher_grade_override,
)
from meridian.teacher_grade_override_workflow import (
    TeacherGradeOverrideBaseStatus,
    TeacherGradeOverrideFreshnessStatus,
    TeacherGradeOverrideSelectedSource,
    TeacherGradeOverrideSourceIntegrityError,
    TeacherGradeOverrideWorkflowError,
    assess_teacher_grade_override_applicability,
    load_teacher_grade_override_source_result,
    resolve_selected_teacher_grade_override_source,
)

EffectiveGradeSource: TypeAlias = Literal["base", "override", "none"]
EffectiveGradeOverrideApplicability: TypeAlias = Literal[
    "no_override",
    "applicable",
    "withdrawn",
    "source_result_changed",
    "source_result_stale",
]
EffectiveGradeOverrideReason: TypeAlias = Literal[
    "no_selected_override",
    "selected_override_withdrawn",
    "source_result_mismatch",
    "source_result_stale",
]

_EFFECTIVE_SOURCES = frozenset({"base", "override", "none"})
_OVERRIDE_APPLICABILITY = frozenset(
    {
        "no_override",
        "applicable",
        "withdrawn",
        "source_result_changed",
        "source_result_stale",
    }
)
_OVERRIDE_REASONS = frozenset(
    {
        "no_selected_override",
        "selected_override_withdrawn",
        "source_result_mismatch",
        "source_result_stale",
    }
)


class EffectiveGradeError(RuntimeError):
    """Base error for deterministic effective Grade resolution."""

    code = "effective_grade.error"


class EffectiveGradeScopeError(EffectiveGradeError, ValueError):
    """Raised when pure effective-Grade inputs are internally inconsistent."""

    code = "effective_grade.scope_invalid"


class EffectiveGradeSourceError(EffectiveGradeError):
    """Raised when the exact selected base Grade/currentness cannot be resolved."""

    code = "effective_grade.source_unavailable"


class EffectiveGradeIntegrityError(EffectiveGradeError):
    """Raised when selected override or historical source state is untrustworthy."""

    code = "effective_grade.integrity_failed"


@dataclass(frozen=True, slots=True)
class EffectiveGradeResolution:
    """Structured effective Grade plus exact base/override provenance."""

    base_result_family: GradeCalculationFamily
    base_result_reference: GradeOverrideSourceResultReference
    base_result_status: TeacherGradeOverrideBaseStatus
    base_grade: Decimal | None
    base_freshness_status: TeacherGradeOverrideFreshnessStatus
    base_freshness_reasons: tuple[str, ...]
    selected_override_reference: TeacherGradeOverrideReference | None
    override_decision: TeacherGradeOverrideDecision | None
    override_applicability: EffectiveGradeOverrideApplicability
    override_reasons: tuple[EffectiveGradeOverrideReason, ...]
    effective_grade: Decimal | None
    effective_source: EffectiveGradeSource

    def __post_init__(self) -> None:
        if not isinstance(
            self.base_result_reference,
            GradeOverrideSourceResultReference,
        ):
            raise EffectiveGradeScopeError(
                "base_result_reference must be GradeOverrideSourceResultReference."
            )
        if self.base_result_family != self.base_result_reference.family:
            raise EffectiveGradeScopeError(
                "base_result_family must match base_result_reference.family."
            )
        _validate_base_value(self.base_result_status, self.base_grade)
        reasons = _freshness_reasons(
            self.base_freshness_status,
            self.base_freshness_reasons,
        )
        object.__setattr__(self, "base_freshness_reasons", reasons)

        reference = self.selected_override_reference
        decision = self.override_decision
        if (reference is None) != (decision is None):
            raise EffectiveGradeScopeError(
                "selected override reference and decision must be present together."
            )
        if decision is not None and reference is not None:
            if teacher_grade_override_reference(decision) != reference:
                raise EffectiveGradeScopeError(
                    "selected override reference must bind exact decision bytes."
                )
            _require_same_logical_scope(self.base_result_reference, decision)

        if self.override_applicability not in _OVERRIDE_APPLICABILITY:
            raise EffectiveGradeScopeError(
                "unsupported effective Grade override applicability."
            )
        override_reasons = tuple(self.override_reasons)
        if any(reason not in _OVERRIDE_REASONS for reason in override_reasons):
            raise EffectiveGradeScopeError(
                "unsupported effective Grade override reason."
            )
        if len(set(override_reasons)) != len(override_reasons):
            raise EffectiveGradeScopeError(
                "effective Grade override reasons must not contain duplicates."
            )
        expected_reasons: dict[
            EffectiveGradeOverrideApplicability,
            tuple[EffectiveGradeOverrideReason, ...],
        ] = {
            "no_override": ("no_selected_override",),
            "applicable": (),
            "withdrawn": ("selected_override_withdrawn",),
            "source_result_changed": ("source_result_mismatch",),
            "source_result_stale": ("source_result_stale",),
        }
        if override_reasons != expected_reasons[self.override_applicability]:
            raise EffectiveGradeScopeError(
                "override_reasons do not match override_applicability."
            )
        if self.override_applicability == "no_override" and decision is not None:
            raise EffectiveGradeScopeError(
                "no_override applicability requires no selected override decision."
            )
        if self.override_applicability != "no_override" and decision is None:
            raise EffectiveGradeScopeError(
                "selected override applicability requires a selected decision."
            )
        object.__setattr__(self, "override_reasons", override_reasons)

        if self.effective_source not in _EFFECTIVE_SOURCES:
            raise EffectiveGradeScopeError("unsupported effective_source.")
        _validate_effective_value(
            effective_source=self.effective_source,
            effective_grade=self.effective_grade,
            base_status=self.base_result_status,
            base_grade=self.base_grade,
            base_freshness=self.base_freshness_status,
            override_applicability=self.override_applicability,
            override_decision=decision,
        )



def resolve_effective_grade(
    selected_source: TeacherGradeOverrideSelectedSource,
    *,
    selected_override_reference: TeacherGradeOverrideReference | None = None,
    selected_override: TeacherGradeOverrideDecision | None = None,
) -> EffectiveGradeResolution:
    """Purely apply #53 precedence to exact selected source/override state."""

    if not isinstance(selected_source, TeacherGradeOverrideSelectedSource):
        raise EffectiveGradeScopeError(
            "selected_source must be TeacherGradeOverrideSelectedSource."
        )
    if (selected_override_reference is None) != (selected_override is None):
        raise EffectiveGradeScopeError(
            "selected override reference and decision must be supplied together."
        )

    source_reference = selected_source.source_result
    if selected_override is None:
        applicability: EffectiveGradeOverrideApplicability = "no_override"
        override_reasons: tuple[EffectiveGradeOverrideReason, ...] = (
            "no_selected_override",
        )
    else:
        assert selected_override_reference is not None
        if teacher_grade_override_reference(selected_override) != (
            selected_override_reference
        ):
            raise EffectiveGradeScopeError(
                "selected override reference does not bind selected decision."
            )
        _require_same_logical_scope(source_reference, selected_override)
        assessed = assess_teacher_grade_override_applicability(
            selected_source,
            selected_override,
        )
        if assessed.status == "applicable":
            applicability = "applicable"
            override_reasons = ()
        elif assessed.status == "withdrawn":
            applicability = "withdrawn"
            override_reasons = ("selected_override_withdrawn",)
        elif assessed.status == "source_mismatch":
            applicability = "source_result_changed"
            override_reasons = ("source_result_mismatch",)
        else:
            applicability = "source_result_stale"
            override_reasons = ("source_result_stale",)

    effective_grade: Decimal | None
    effective_source: EffectiveGradeSource
    if applicability == "applicable":
        assert selected_override is not None
        assert selected_override.replacement_grade is not None
        effective_grade = selected_override.replacement_grade
        effective_source = "override"
    elif (
        selected_source.freshness_status == "current"
        and selected_source.source_status == "calculated"
    ):
        effective_grade = selected_source.base_grade
        effective_source = "base"
    else:
        effective_grade = None
        effective_source = "none"

    return EffectiveGradeResolution(
        base_result_family=source_reference.family,
        base_result_reference=source_reference,
        base_result_status=selected_source.source_status,
        base_grade=selected_source.base_grade,
        base_freshness_status=selected_source.freshness_status,
        base_freshness_reasons=selected_source.freshness_reasons,
        selected_override_reference=selected_override_reference,
        override_decision=selected_override,
        override_applicability=applicability,
        override_reasons=override_reasons,
        effective_grade=effective_grade,
        effective_source=effective_source,
    )



def resolve_current_effective_grade(
    workspace_root: str | Path,
    class_id: str,
    student_id: str,
    target_period: AcademicPeriodRef,
    calendar_revision: int,
    calculation_family: GradeCalculationFamily,
    *,
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None = None,
) -> EffectiveGradeResolution:
    """Resolve effective Grade from exact canonical selected state only."""

    try:
        selected_source = resolve_selected_teacher_grade_override_source(
            workspace_root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
            calculation_family,
            work_evidence=work_evidence,
        )
    except TeacherGradeOverrideWorkflowError as error:
        raise EffectiveGradeSourceError(
            f"Selected base Grade/currentness could not be resolved: {error}"
        ) from error

    try:
        stored_override = load_current_teacher_grade_override(
            workspace_root,
            class_id,
            student_id,
            target_period,
            calendar_revision,
            calculation_family,
        )
    except TeacherGradeOverrideStorageError as error:
        raise EffectiveGradeIntegrityError(
            f"Selected teacher Grade override state is invalid: {error}"
        ) from error

    if stored_override is None:
        return resolve_effective_grade(selected_source)

    try:
        load_teacher_grade_override_source_result(
            workspace_root,
            stored_override.decision.source_result,
        )
    except TeacherGradeOverrideSourceIntegrityError as error:
        raise EffectiveGradeIntegrityError(
            "Selected override references an unavailable or corrupt historical "
            "Grade result."
        ) from error
    except TeacherGradeOverrideWorkflowError as error:
        raise EffectiveGradeIntegrityError(
            f"Selected override source provenance could not be verified: {error}"
        ) from error

    return resolve_effective_grade(
        selected_source,
        selected_override_reference=stored_override.reference,
        selected_override=stored_override.decision,
    )



def _validate_base_value(
    status: TeacherGradeOverrideBaseStatus,
    grade: Decimal | None,
) -> None:
    if status == "calculated":
        if not isinstance(grade, Decimal) or not grade.is_finite():
            raise EffectiveGradeScopeError(
                "calculated base result requires an exact finite base_grade."
            )
    elif status in {"blocked", "insufficient"}:
        if grade is not None:
            raise EffectiveGradeScopeError(
                "blocked/insufficient base result must not carry base_grade."
            )
    else:
        raise EffectiveGradeScopeError("unsupported base_result_status.")



def _freshness_reasons(
    status: TeacherGradeOverrideFreshnessStatus,
    values: tuple[str, ...],
) -> tuple[str, ...]:
    try:
        reasons = tuple(values)
    except TypeError as error:
        raise EffectiveGradeScopeError(
            "base_freshness_reasons must be iterable."
        ) from error
    if any(not isinstance(reason, str) or not reason for reason in reasons):
        raise EffectiveGradeScopeError(
            "base_freshness_reasons must contain nonblank strings."
        )
    if len(set(reasons)) != len(reasons):
        raise EffectiveGradeScopeError(
            "base_freshness_reasons must not contain duplicates."
        )
    if status == "current":
        if reasons:
            raise EffectiveGradeScopeError(
                "current base freshness must not carry reasons."
            )
    elif status == "stale":
        if not reasons:
            raise EffectiveGradeScopeError(
                "stale base freshness requires at least one reason."
            )
    else:
        raise EffectiveGradeScopeError("unsupported base_freshness_status.")
    return reasons



def _require_same_logical_scope(
    source: GradeOverrideSourceResultReference,
    decision: TeacherGradeOverrideDecision,
) -> None:
    reference = source.reference
    source_scope = (
        reference.class_id,
        reference.student_id,
        reference.school_year,
        reference.period_id,
        reference.calendar_revision,
        source.family,
    )
    decision_scope = (
        decision.class_id,
        decision.student_id,
        decision.target_period.school_year,
        decision.target_period.period_id,
        decision.calendar_revision,
        decision.calculation_family,
    )
    if source_scope != decision_scope:
        raise EffectiveGradeScopeError(
            "selected base and selected override must share exact logical scope."
        )



def _validate_effective_value(
    *,
    effective_source: EffectiveGradeSource,
    effective_grade: Decimal | None,
    base_status: TeacherGradeOverrideBaseStatus,
    base_grade: Decimal | None,
    base_freshness: TeacherGradeOverrideFreshnessStatus,
    override_applicability: EffectiveGradeOverrideApplicability,
    override_decision: TeacherGradeOverrideDecision | None,
) -> None:
    if effective_source == "override":
        if override_applicability != "applicable" or override_decision is None:
            raise EffectiveGradeScopeError(
                "effective_source=override requires an applicable selected override."
            )
        replacement = override_decision.replacement_grade
        if replacement is None or effective_grade != replacement:
            raise EffectiveGradeScopeError(
                "effective override Grade must equal exact replacement_grade."
            )
        return
    if effective_source == "base":
        if base_freshness != "current" or base_status != "calculated":
            raise EffectiveGradeScopeError(
                "effective_source=base requires current calculated base authority."
            )
        if effective_grade != base_grade:
            raise EffectiveGradeScopeError(
                "effective base Grade must equal exact base_grade."
            )
        if override_applicability == "applicable":
            raise EffectiveGradeScopeError(
                "applicable active override must take precedence over base Grade."
            )
        return
    if effective_grade is not None:
        raise EffectiveGradeScopeError(
            "effective_source=none requires effective_grade=None."
        )
    if (
        base_freshness == "current"
        and base_status == "calculated"
        and override_applicability != "applicable"
    ):
        raise EffectiveGradeScopeError(
            "current calculated base must govern when no applicable override exists."
        )


__all__ = [
    "EffectiveGradeError",
    "EffectiveGradeIntegrityError",
    "EffectiveGradeOverrideApplicability",
    "EffectiveGradeOverrideReason",
    "EffectiveGradeResolution",
    "EffectiveGradeScopeError",
    "EffectiveGradeSource",
    "EffectiveGradeSourceError",
    "resolve_current_effective_grade",
    "resolve_effective_grade",
]
