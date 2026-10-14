from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.marking_period_readiness as readiness
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.grade_report_preview import GradeReportPreview, GradeReportPreviewRow
from meridian.proficiency_attention import (
    MeridianAttentionItem,
    build_meridian_attention_summary,
)
from meridian.report_export_roster import (
    EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
    EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
    ExportRosterObservation,
    ExportRosterObservedValue,
    ExportRosterStudentObservation,
)

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "mp1")
NOW = datetime(2026, 10, 13, 4, 0, tzinfo=UTC)


def _target(student_id: str) -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id=student_id,
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="standards_based",
    )


def _report(student_id: str = "student_001") -> GradeReportPreview:
    return GradeReportPreview(
        (
            GradeReportPreviewRow(
                target=_target(student_id),
                status="unavailable",
                explanation=None,
                observation=None,
                unavailable_reason="no_selected_grade",
            ),
        )
    )


def _roster(student_id: str = "student_001") -> ExportRosterObservation:
    return ExportRosterObservation(
        schema_version=EXPORT_ROSTER_OBSERVATION_SCHEMA_VERSION,
        record_type=EXPORT_ROSTER_OBSERVATION_RECORD_TYPE,
        class_id=CLASS_ID,
        source_fields=("roster.display_name",),
        students=(
            ExportRosterStudentObservation(
                student_id,
                (
                    ExportRosterObservedValue(
                        "roster.display_name",
                        "Avery Chen",
                    ),
                ),
            ),
        ),
    )


def test_no_selected_grade_is_review_needed_without_sis_finalization_claim() -> None:
    preview = readiness.compose_marking_period_readiness(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        live_grade_report=_report(),
        live_grade_report_sha256="a" * 64,
        roster_observation=_roster(),
        attention_summary=build_meridian_attention_summary(()),
        current_snapshot_reference=None,
        current_selection_reference=None,
        generated_at=NOW,
    )

    assert preview.report_kind == "marking_period_readiness"
    assert preview.rows[0].values[3] == "no_selected_grade"
    assert preview.rows[0].values[11] == "REVIEW_NEEDED"
    rendered = " ".join(preview.summary).lower()
    assert "review needed before external marking-period close" in rendered
    assert "does not mean an sis is ready" in rendered


def test_clean_state_uses_bounded_clear_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        readiness,
        "_student_state",
        lambda *args, **kwargs: readiness.ReadinessStudentState(
            student_id="student_001",
            student_name="Avery Chen",
            calculation_family="standards_based",
            grade_status="calculated",
            effective_grade="91",
            freshness_status="current",
            active_override=False,
            evidence_facts=(),
            proficiency_insufficient=False,
            checkpoint_change="unchanged",
            review_reasons=(),
        ),
    )

    preview = readiness.compose_marking_period_readiness(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        live_grade_report=_report(),
        live_grade_report_sha256="b" * 64,
        roster_observation=_roster(),
        attention_summary=build_meridian_attention_summary(()),
        current_snapshot_reference=None,
        current_selection_reference=None,
        generated_at=NOW,
    )

    assert preview.rows[0].values[11] == "CLEAR"
    assert "No unresolved Meridian reporting blockers detected" in preview.summary


@pytest.mark.parametrize(
    "code",
    [
        "meridian_grade_result_stale",
        "meridian_reporting_publication_changed",
        "meridian_reporting_snapshot_refresh_needed",
        "meridian_reporting_snapshot_selection_pending",
    ],
)
def test_existing_grade_report_attention_routes_to_review(
    monkeypatch: pytest.MonkeyPatch,
    code: str,
) -> None:
    monkeypatch.setattr(
        readiness,
        "_student_state",
        lambda *args, **kwargs: readiness.ReadinessStudentState(
            student_id="student_001",
            student_name="Avery Chen",
            calculation_family="standards_based",
            grade_status="calculated",
            effective_grade="91",
            freshness_status="current",
            active_override=True,
            evidence_facts=(),
            proficiency_insufficient=False,
            checkpoint_change=None,
            review_reasons=(),
        ),
    )
    attention = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code=code,  # type: ignore[arg-type]
                count=1,
                class_id=CLASS_ID,
            ),
        )
    )

    preview = readiness.compose_marking_period_readiness(
        class_id=CLASS_ID,
        target_period=PERIOD,
        calendar_revision=1,
        live_grade_report=_report(),
        live_grade_report_sha256="c" * 64,
        roster_observation=_roster(),
        attention_summary=attention,
        current_snapshot_reference=None,
        current_selection_reference=None,
        generated_at=NOW,
    )

    assert "Review needed before external marking-period close" in preview.summary
    assert preview.rows[0].values[6] == "yes"
    assert any(item.code == code for item in preview.diagnostics)
