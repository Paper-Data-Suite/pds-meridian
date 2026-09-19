"""Explicit multi-student Grade report-preview composition for Meridian v0.3.

The report preview is only an aggregation of caller-supplied Grade-preview
requests.  It never discovers a roster, persists ReportingSnapshots, exports an
official Grade, or converts source/integrity failures into silent absence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from pds_core.academic_periods import academic_period_ref_to_dict

from meridian.conventional_grade_assembly import ConventionalGradeWorkEvidenceSpec
from meridian.conventional_grade_explanation import (
    ConventionalGradePreviewExplanation,
    conventional_grade_observation,
    conventional_grade_preview_explanation_to_dict,
)
from meridian.current_grade_preview import (
    CurrentGradePreviewExplanation,
    explain_current_grade_preview,
)
from meridian.grade_preview_explanation import (
    GradePreviewExplanation,
    GradePreviewObservation,
    GradePreviewTarget,
    GradePreviewTargetError,
    GradePreviewTargetNotFoundError,
    grade_preview_observation_to_dict,
)
from meridian.hybrid_grade_explanation import (
    HybridGradePreviewExplanation,
    hybrid_grade_observation,
    hybrid_grade_preview_explanation_to_dict,
)
from meridian.standards_grade_explanation import (
    StandardsGradePreviewExplanation,
    standards_grade_observation,
    standards_grade_preview_explanation_to_dict,
)

GradeReportPreviewRowStatus: TypeAlias = Literal["available", "unavailable"]
GradeReportPreviewUnavailableReason: TypeAlias = Literal["no_selected_grade"]


@dataclass(frozen=True, slots=True)
class GradeReportPreviewRequest:
    """One explicit student/family request included in a report preview."""

    target: GradePreviewTarget
    work_evidence: tuple[ConventionalGradeWorkEvidenceSpec, ...] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, GradePreviewTarget):
            raise GradePreviewTargetError(
                "report preview request target must be GradePreviewTarget."
            )
        evidence = self.work_evidence
        if self.target.calculation_family in {"conventional", "hybrid"}:
            if evidence is None:
                raise GradePreviewTargetError(
                    f"{self.target.calculation_family} report row requires explicit "
                    "work_evidence."
                )
        elif evidence is not None:
            raise GradePreviewTargetError(
                "standards-based report row does not accept work_evidence."
            )
        if evidence is not None:
            if not isinstance(evidence, tuple) or any(
                not isinstance(item, ConventionalGradeWorkEvidenceSpec)
                for item in evidence
            ):
                raise GradePreviewTargetError(
                    "work_evidence must be a tuple of "
                    "ConventionalGradeWorkEvidenceSpec values."
                )


@dataclass(frozen=True, slots=True)
class GradeReportPreviewRow:
    """One available or explicitly unavailable row in a report preview."""

    target: GradePreviewTarget
    status: GradeReportPreviewRowStatus
    explanation: CurrentGradePreviewExplanation | None
    observation: GradePreviewObservation | None
    unavailable_reason: GradeReportPreviewUnavailableReason | None

    def __post_init__(self) -> None:
        if not isinstance(self.target, GradePreviewTarget):
            raise GradePreviewTargetError("report row target is invalid.")
        if self.status == "available":
            if self.explanation is None or self.observation is None:
                raise GradePreviewTargetError(
                    "available report row requires explanation and observation."
                )
            if self.unavailable_reason is not None:
                raise GradePreviewTargetError(
                    "available report row must not carry unavailable_reason."
                )
            if _explanation_target(self.explanation) != self.target:
                raise GradePreviewTargetError(
                    "report row explanation target does not match row target."
                )
            if self.observation.target != self.target:
                raise GradePreviewTargetError(
                    "report row observation target does not match row target."
                )
        elif self.status == "unavailable":
            if self.explanation is not None or self.observation is not None:
                raise GradePreviewTargetError(
                    "unavailable report row must not carry Grade explanation state."
                )
            if self.unavailable_reason != "no_selected_grade":
                raise GradePreviewTargetError(
                    "unavailable report row requires no_selected_grade reason."
                )
        else:
            raise GradePreviewTargetError("unsupported report row status.")


@dataclass(frozen=True, slots=True)
class GradeReportPreviewSummary:
    """Deterministic aggregate counts over report rows only."""

    requested_count: int
    available_count: int
    unavailable_count: int
    base_calculated_count: int
    base_blocked_count: int
    base_insufficient_count: int
    current_count: int
    stale_count: int
    effective_numeric_count: int
    effective_nonnumeric_count: int
    effective_base_count: int
    effective_override_count: int
    effective_none_count: int

    def __post_init__(self) -> None:
        values = (
            self.requested_count,
            self.available_count,
            self.unavailable_count,
            self.base_calculated_count,
            self.base_blocked_count,
            self.base_insufficient_count,
            self.current_count,
            self.stale_count,
            self.effective_numeric_count,
            self.effective_nonnumeric_count,
            self.effective_base_count,
            self.effective_override_count,
            self.effective_none_count,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise GradePreviewTargetError(
                "report summary counts must be nonnegative integers."
            )
        if self.available_count + self.unavailable_count != self.requested_count:
            raise GradePreviewTargetError(
                "report summary availability counts must equal requested_count."
            )
        if (
            self.base_calculated_count
            + self.base_blocked_count
            + self.base_insufficient_count
            != self.available_count
        ):
            raise GradePreviewTargetError(
                "report summary base-status counts must equal available_count."
            )
        if self.current_count + self.stale_count != self.available_count:
            raise GradePreviewTargetError(
                "report summary freshness counts must equal available_count."
            )
        if (
            self.effective_numeric_count + self.effective_nonnumeric_count
            != self.available_count
        ):
            raise GradePreviewTargetError(
                "report summary effective-value counts must equal available_count."
            )
        if (
            self.effective_base_count
            + self.effective_override_count
            + self.effective_none_count
            != self.available_count
        ):
            raise GradePreviewTargetError(
                "report summary effective-source counts must equal available_count."
            )


@dataclass(frozen=True, slots=True)
class GradeReportPreview:
    """Deterministic read-only report over only explicitly requested rows."""

    rows: tuple[GradeReportPreviewRow, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.rows, tuple) or any(
            not isinstance(row, GradeReportPreviewRow) for row in self.rows
        ):
            raise GradePreviewTargetError(
                "report preview rows must be a tuple of GradeReportPreviewRow values."
            )
        keys = tuple(_target_key(row.target) for row in self.rows)
        if len(set(keys)) != len(keys):
            raise GradePreviewTargetError(
                "report preview must not contain duplicate exact Grade targets."
            )
        canonical = tuple(
            sorted(self.rows, key=lambda row: _target_key(row.target))
        )
        if canonical != self.rows:
            raise GradePreviewTargetError(
                "report preview rows must use deterministic canonical target order."
            )

    @property
    def summary(self) -> GradeReportPreviewSummary:
        """Return deterministic aggregate counts over the frozen rows."""

        return _report_summary(self.rows)


def explain_grade_report_preview(
    workspace_root: str | Path,
    requests: tuple[GradeReportPreviewRequest, ...],
) -> GradeReportPreview:
    """Build a report preview from only caller-supplied student Grade requests."""

    if not isinstance(requests, tuple) or any(
        not isinstance(request, GradeReportPreviewRequest) for request in requests
    ):
        raise GradePreviewTargetError(
            "requests must be a tuple of GradeReportPreviewRequest values."
        )
    keys = tuple(_target_key(request.target) for request in requests)
    if len(set(keys)) != len(keys):
        raise GradePreviewTargetError(
            "report preview requests must not contain duplicate exact Grade targets."
        )

    rows: list[GradeReportPreviewRow] = []
    ordered_requests = tuple(
        sorted(requests, key=lambda item: _target_key(item.target))
    )
    for request in ordered_requests:
        try:
            explanation = explain_current_grade_preview(
                workspace_root,
                request.target,
                work_evidence=request.work_evidence,
            )
        except GradePreviewTargetNotFoundError:
            rows.append(
                GradeReportPreviewRow(
                    target=request.target,
                    status="unavailable",
                    explanation=None,
                    observation=None,
                    unavailable_reason="no_selected_grade",
                )
            )
            continue
        observation = _observation_from_explanation(explanation)
        rows.append(
            GradeReportPreviewRow(
                target=request.target,
                status="available",
                explanation=explanation,
                observation=observation,
                unavailable_reason=None,
            )
        )
    return GradeReportPreview(tuple(rows))


def grade_report_preview_to_dict(value: GradeReportPreview) -> dict[str, object]:
    """Return deterministic JSON-native data for one report preview."""

    if not isinstance(value, GradeReportPreview):
        raise GradePreviewTargetError("value must be GradeReportPreview.")
    return {
        "summary": _summary_to_dict(value.summary),
        "rows": [
            {
                "target": _target_to_dict(row.target),
                "status": row.status,
                "unavailable_reason": row.unavailable_reason,
                "explanation": (
                    _explanation_to_dict(row.explanation)
                    if row.explanation is not None
                    else None
                ),
                "observation": (
                    grade_preview_observation_to_dict(row.observation)
                    if row.observation is not None
                    else None
                ),
            }
            for row in value.rows
        ]
    }


def grade_report_preview_to_json_bytes(value: GradeReportPreview) -> bytes:
    """Return canonical UTF-8 JSON bytes for one report preview."""

    return _canonical_json_bytes(grade_report_preview_to_dict(value))


def _report_summary(
    rows: tuple[GradeReportPreviewRow, ...],
) -> GradeReportPreviewSummary:
    available = tuple(row for row in rows if row.status == "available")
    common = tuple(
        _explanation_common(row.explanation)
        for row in available
        if row.explanation is not None
    )
    return GradeReportPreviewSummary(
        requested_count=len(rows),
        available_count=len(available),
        unavailable_count=len(rows) - len(available),
        base_calculated_count=sum(
            item.base_result_status == "calculated" for item in common
        ),
        base_blocked_count=sum(
            item.base_result_status == "blocked" for item in common
        ),
        base_insufficient_count=sum(
            item.base_result_status == "insufficient" for item in common
        ),
        current_count=sum(
            item.base_freshness_status == "current" for item in common
        ),
        stale_count=sum(item.base_freshness_status == "stale" for item in common),
        effective_numeric_count=sum(
            item.effective_grade is not None for item in common
        ),
        effective_nonnumeric_count=sum(item.effective_grade is None for item in common),
        effective_base_count=sum(item.effective_source == "base" for item in common),
        effective_override_count=sum(
            item.effective_source == "override" for item in common
        ),
        effective_none_count=sum(item.effective_source == "none" for item in common),
    )


def _summary_to_dict(value: GradeReportPreviewSummary) -> dict[str, object]:
    return {
        "requested_count": value.requested_count,
        "available_count": value.available_count,
        "unavailable_count": value.unavailable_count,
        "base_calculated_count": value.base_calculated_count,
        "base_blocked_count": value.base_blocked_count,
        "base_insufficient_count": value.base_insufficient_count,
        "current_count": value.current_count,
        "stale_count": value.stale_count,
        "effective_numeric_count": value.effective_numeric_count,
        "effective_nonnumeric_count": value.effective_nonnumeric_count,
        "effective_base_count": value.effective_base_count,
        "effective_override_count": value.effective_override_count,
        "effective_none_count": value.effective_none_count,
    }


def _explanation_common(
    value: CurrentGradePreviewExplanation,
) -> GradePreviewExplanation:
    if isinstance(
        value,
        (
            ConventionalGradePreviewExplanation,
            StandardsGradePreviewExplanation,
            HybridGradePreviewExplanation,
        ),
    ):
        return value.common
    raise GradePreviewTargetError("unsupported report row Grade explanation family.")


def _observation_from_explanation(
    value: CurrentGradePreviewExplanation,
) -> GradePreviewObservation:
    if isinstance(value, ConventionalGradePreviewExplanation):
        return conventional_grade_observation(value)
    if isinstance(value, StandardsGradePreviewExplanation):
        return standards_grade_observation(value)
    if isinstance(value, HybridGradePreviewExplanation):
        return hybrid_grade_observation(value)
    raise GradePreviewTargetError("unsupported report row Grade explanation family.")


def _explanation_target(value: CurrentGradePreviewExplanation) -> GradePreviewTarget:
    if isinstance(
        value,
        (
            ConventionalGradePreviewExplanation,
            StandardsGradePreviewExplanation,
            HybridGradePreviewExplanation,
        ),
    ):
        return value.common.target
    raise GradePreviewTargetError("unsupported report row Grade explanation family.")


def _explanation_to_dict(
    value: CurrentGradePreviewExplanation,
) -> dict[str, object]:
    if isinstance(value, ConventionalGradePreviewExplanation):
        return conventional_grade_preview_explanation_to_dict(value)
    if isinstance(value, StandardsGradePreviewExplanation):
        return standards_grade_preview_explanation_to_dict(value)
    if isinstance(value, HybridGradePreviewExplanation):
        return hybrid_grade_preview_explanation_to_dict(value)
    raise GradePreviewTargetError("unsupported report row Grade explanation family.")


def _target_key(value: GradePreviewTarget) -> tuple[str, str, str, str, int, str]:
    return (
        value.class_id,
        value.student_id,
        value.target_period.school_year,
        value.target_period.period_id,
        value.calendar_revision,
        value.calculation_family,
    )


def _target_to_dict(value: GradePreviewTarget) -> dict[str, object]:
    return {
        "class_id": value.class_id,
        "student_id": value.student_id,
        "target_period": academic_period_ref_to_dict(value.target_period),
        "calendar_revision": value.calendar_revision,
        "calculation_family": value.calculation_family,
    }


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


__all__ = [
    "GradeReportPreview",
    "GradeReportPreviewRequest",
    "GradeReportPreviewRow",
    "GradeReportPreviewSummary",
    "GradeReportPreviewRowStatus",
    "GradeReportPreviewUnavailableReason",
    "explain_grade_report_preview",
    "grade_report_preview_to_dict",
    "grade_report_preview_to_json_bytes",
]
