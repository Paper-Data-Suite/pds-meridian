from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.grade_report_preview as report
from meridian.conventional_grade import ConventionalGradeResultReference
from meridian.grade_policy import GradePolicyReference
from meridian.grade_policy_activation import GradePolicyActivationReference
from meridian.grade_preview_explanation import (
    GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
    GradePreviewBasisEntry,
    GradePreviewObservation,
    GradePreviewSourceError,
    GradePreviewTarget,
    GradePreviewTargetError,
    GradePreviewTargetNotFoundError,
)
from meridian.standards_grade_result import StandardsGradeResultReference
from meridian.teacher_grade_override import GradeOverrideSourceResultReference

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")


def _target(
    student_id: str,
    family: str = "standards_based",
) -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family=family,  # type: ignore[arg-type]
    )


def _observation(target: GradePreviewTarget) -> GradePreviewObservation:
    common = dict(
        class_id=target.class_id,
        student_id=target.student_id,
        school_year=target.target_period.school_year,
        period_id=target.target_period.period_id,
        calendar_revision=target.calendar_revision,
        result_revision=1,
        result_sha256="a" * 64,
    )
    if target.calculation_family == "conventional":
        reference = ConventionalGradeResultReference(**common)
    else:
        reference = StandardsGradeResultReference(**common)
    source = GradeOverrideSourceResultReference(
        target.calculation_family,
        reference,
    )
    return GradePreviewObservation(
        schema_version=GRADE_PREVIEW_OBSERVATION_SCHEMA_VERSION,
        target=target,
        base_result_reference=source,
        base_result_status="calculated",
        base_grade=Decimal("90"),
        base_freshness_status="current",
        base_freshness_reasons=(),
        algorithm_version="1",
        calculation_fingerprint="b" * 64,
        inputs_sha256="c" * 64,
        activation_reference=GradePolicyActivationReference(
            target.class_id,
            target.target_period.school_year,
            target.target_period.period_id,
            1,
            "d" * 64,
        ),
        policy_reference=GradePolicyReference(
            target.class_id,
            "course_grade",
            1,
            "e" * 64,
        ),
        selected_override_reference=None,
        override_applicability="no_override",
        override_replacement_grade=None,
        effective_grade=Decimal("90"),
        effective_source="base",
        basis_entries=(
            GradePreviewBasisEntry(
                "algorithm",
                target.calculation_family,
                "f" * 64,
            ),
        ),
    )


def test_request_requires_explicit_work_evidence_only_for_relevant_families() -> None:
    standards = report.GradeReportPreviewRequest(_target("s1"))
    conventional = report.GradeReportPreviewRequest(
        _target("s1", "conventional"),
        work_evidence=(),
    )

    assert standards.work_evidence is None
    assert conventional.work_evidence == ()
    with pytest.raises(GradePreviewTargetError, match="requires explicit"):
        report.GradeReportPreviewRequest(_target("s2", "conventional"))
    with pytest.raises(GradePreviewTargetError, match="does not accept"):
        report.GradeReportPreviewRequest(_target("s2"), work_evidence=())


def test_report_preview_uses_only_explicit_requests_and_allows_mixed_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = _target("s1")
    second = _target("s2")
    first_explanation = SimpleNamespace(name="first")
    calls: list[GradePreviewTarget] = []

    def explain(*args: object, **kwargs: object):
        target = args[1]
        assert isinstance(target, GradePreviewTarget)
        calls.append(target)
        if target == second:
            raise GradePreviewTargetNotFoundError("no selected Grade")
        return first_explanation

    monkeypatch.setattr(report, "explain_current_grade_preview", explain)
    monkeypatch.setattr(
        report,
        "_explanation_target",
        lambda value: first,
    )
    monkeypatch.setattr(
        report,
        "_observation_from_explanation",
        lambda value: _observation(first),
    )
    monkeypatch.setattr(
        report,
        "_explanation_common",
        lambda value: SimpleNamespace(
            base_result_status="calculated",
            base_freshness_status="stale",
            effective_grade=Decimal("91.25"),
            effective_source="override",
        ),
    )

    preview = report.explain_grade_report_preview(
        ".",
        (
            report.GradeReportPreviewRequest(second),
            report.GradeReportPreviewRequest(first),
        ),
    )

    assert calls == [first, second]
    assert tuple(row.target for row in preview.rows) == (first, second)
    assert preview.rows[0].status == "available"
    assert preview.rows[1].status == "unavailable"
    assert preview.rows[1].unavailable_reason == "no_selected_grade"
    assert preview.summary.requested_count == 2
    assert preview.summary.available_count == 1
    assert preview.summary.unavailable_count == 1
    assert preview.summary.base_calculated_count == 1
    assert preview.summary.stale_count == 1
    assert preview.summary.effective_numeric_count == 1
    assert preview.summary.effective_override_count == 1


def test_only_target_not_found_is_converted_to_unavailable_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target("s1")

    monkeypatch.setattr(
        report,
        "explain_current_grade_preview",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            GradePreviewSourceError("current basis unavailable")
        ),
    )

    with pytest.raises(GradePreviewSourceError, match="current basis unavailable"):
        report.explain_grade_report_preview(
            ".",
            (report.GradeReportPreviewRequest(target),),
        )


def test_duplicate_exact_requests_are_rejected_before_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target("s1")
    called = False

    def explain(*args: object, **kwargs: object) -> object:
        nonlocal called
        called = True
        return object()

    monkeypatch.setattr(report, "explain_current_grade_preview", explain)

    with pytest.raises(GradePreviewTargetError, match="duplicate exact"):
        report.explain_grade_report_preview(
            ".",
            (
                report.GradeReportPreviewRequest(target),
                report.GradeReportPreviewRequest(target),
            ),
        )
    assert called is False


def test_unavailable_report_serialization_is_deterministic() -> None:
    target = _target("s1")
    preview = report.GradeReportPreview(
        (
            report.GradeReportPreviewRow(
                target=target,
                status="unavailable",
                explanation=None,
                observation=None,
                unavailable_reason="no_selected_grade",
            ),
        )
    )

    first = report.grade_report_preview_to_json_bytes(preview)
    second = report.grade_report_preview_to_json_bytes(preview)

    assert first == second
    assert first.endswith(b"\n")
    assert b'"status":"unavailable"' in first
    assert b'"unavailable_reason":"no_selected_grade"' in first
    assert b'"requested_count":1' in first
    assert b'"unavailable_count":1' in first


def test_target_not_found_error_has_distinct_public_code() -> None:
    error = GradePreviewTargetNotFoundError("missing")

    assert isinstance(error, GradePreviewSourceError)
    assert error.code == "grade_preview.target_not_found"
