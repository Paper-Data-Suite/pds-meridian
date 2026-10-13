from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from meridian.reporting_snapshot_preview import (
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.student_grade_justification import (
    StudentGradeJustificationValidationError,
    compose_student_grade_justification,
)
from meridian.teacher_report_render import render_teacher_report
from tests import test_reporting_snapshot_preview_issue55 as snapshot_support

NOW = datetime(2026, 10, 12, 23, 0, tzinfo=UTC)


@pytest.mark.parametrize("family", ["conventional", "standards_based", "hybrid"])
def test_exact_rich_grade_explanation_composes_human_readable_report(
    family: str,
) -> None:
    content, observation = snapshot_support._available_preview_bytes(family)
    frozen = frozen_grade_report_preview_from_json_bytes(content)
    row = frozen.rows[0]
    assert row.explanation_json is not None
    explanation = json.loads(row.explanation_json.decode("utf-8"))

    report = compose_student_grade_justification(
        observation=observation,
        explanation=explanation,
        source_mode="current",
        generated_at=NOW,
    )

    assert report.report_kind == "student_current_grade_justification"
    assert report.class_id == observation.target.class_id
    kinds = {source.source_kind for source in report.source_references}
    assert "grade_result" in kinds
    assert "grade_explanation" in kinds

    markdown = render_teacher_report(report, "markdown")
    assert b"Student Grade Justification" in markdown
    assert b"raw protected student work is not reproduced" in markdown
    assert observation.target.student_id.encode() in markdown


def test_snapshot_mode_requires_exact_snapshot_authority() -> None:
    content, observation = snapshot_support._available_preview_bytes("conventional")
    frozen = frozen_grade_report_preview_from_json_bytes(content)
    row = frozen.rows[0]
    assert row.explanation_json is not None
    explanation = json.loads(row.explanation_json.decode("utf-8"))

    with pytest.raises(
        StudentGradeJustificationValidationError,
        match="snapshot mode requires",
    ):
        compose_student_grade_justification(
            observation=observation,
            explanation=explanation,
            source_mode="snapshot",
            generated_at=NOW,
        )


def test_standards_report_preserves_nonnumeric_insufficient_state() -> None:
    content, observation = snapshot_support._available_preview_bytes("standards_based")
    frozen = frozen_grade_report_preview_from_json_bytes(content)
    row = frozen.rows[0]
    assert row.explanation_json is not None
    explanation = json.loads(row.explanation_json.decode("utf-8"))

    report = compose_student_grade_justification(
        observation=observation,
        explanation=explanation,
        source_mode="current",
        generated_at=NOW,
    )

    values = tuple(
        cell
        for report_row in report.rows
        for cell in report_row.values
        if cell is not None
    )
    assert "insufficient" in values
    assert any(item.code == "grade.nonnumeric" for item in report.diagnostics)
