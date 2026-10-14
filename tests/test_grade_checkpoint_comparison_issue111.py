from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from pds_core.academic_periods import AcademicPeriodRef

from meridian.grade_checkpoint_comparison import (
    CheckpointSideRow,
    compose_grade_checkpoint_comparison,
)
from meridian.grade_preview_comparison import (
    PriorReportingSnapshotGradeBasis,
    compare_grade_preview_basis,
)
from meridian.teacher_report import TeacherReportSourceReference
from tests import test_grade_preview_comparison as support

NOW = datetime(2026, 10, 13, 2, 45, tzinfo=UTC)


def _source(kind: str, source_id: str, digit: str) -> TeacherReportSourceReference:
    return TeacherReportSourceReference(kind, source_id, digit * 64)


def test_numeric_grade_movement_reuses_existing_comparison_delta() -> None:
    prior = support._observation()
    current = replace(
        prior,
        base_grade=Decimal("91.25"),
        effective_grade=Decimal("91.25"),
    )
    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(prior),
    )
    preview = compose_grade_checkpoint_comparison(
        class_id=support.CLASS_ID,
        target_period=support.PERIOD,
        calendar_revision=1,
        prior_rows=(CheckpointSideRow(prior.target, "available", prior, None),),
        current_rows=(CheckpointSideRow(current.target, "available", current, None),),
        comparisons=(comparison,),
        source_references=(
            _source("reporting_snapshot", "prior", "1"),
            _source("live_grade_report", "current", "2"),
        ),
        generated_at=NOW,
        comparison_basis="snapshot_to_current",
    )

    row = preview.rows[0].values
    assert row[4] == "91.25"
    assert row[5] == "3.05"
    assert row[8] == "INCREASED"
    assert "effective_grade_changed" in str(row[9])


def test_nonnumeric_material_change_is_needs_review_not_fake_delta() -> None:
    prior = support._observation()
    current = replace(
        prior,
        base_freshness_status="stale",
        base_freshness_reasons=("inputs_changed",),
        effective_grade=None,
        effective_source="none",
    )
    comparison = compare_grade_preview_basis(
        current,
        PriorReportingSnapshotGradeBasis(prior),
    )
    preview = compose_grade_checkpoint_comparison(
        class_id=support.CLASS_ID,
        target_period=support.PERIOD,
        calendar_revision=1,
        prior_rows=(CheckpointSideRow(prior.target, "available", prior, None),),
        current_rows=(CheckpointSideRow(current.target, "available", current, None),),
        comparisons=(comparison,),
        source_references=(
            _source("reporting_snapshot", "prior", "3"),
            _source("live_grade_report", "current", "4"),
        ),
        generated_at=NOW,
        comparison_basis="snapshot_to_current",
    )

    row = preview.rows[0].values
    assert row[5] is None
    assert row[8] == "NEEDS_REVIEW"
    assert "freshness_changed" in str(row[9])


def test_unavailable_to_unavailable_is_preserved_without_synthetic_grade_diff() -> None:
    target = support._target()
    preview = compose_grade_checkpoint_comparison(
        class_id=support.CLASS_ID,
        target_period=AcademicPeriodRef("2026-2027", "q1"),
        calendar_revision=1,
        prior_rows=(
            CheckpointSideRow(
                target,
                "unavailable",
                None,
                "no_selected_grade",
            ),
        ),
        current_rows=(
            CheckpointSideRow(
                target,
                "unavailable",
                None,
                "no_selected_grade",
            ),
        ),
        comparisons=(),
        source_references=(
            _source("reporting_snapshot", "prior", "5"),
            _source("reporting_snapshot", "current", "6"),
        ),
        generated_at=NOW,
        comparison_basis="snapshot_to_snapshot",
    )

    assert preview.rows[0].values[8] == "UNAVAILABLE_UNCHANGED"
    assert preview.rows[0].values[9] == "none"
