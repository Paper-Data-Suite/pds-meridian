from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import meridian.student_grade_justification as justification
from meridian.reporting_snapshot import ReportingSnapshotReference
from meridian.reporting_snapshot_preview import (
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.student_grade_justification import (
    StudentGradeJustificationAmbiguousError,
    build_snapshot_student_grade_justification,
)
from tests import test_reporting_snapshot_preview_issue55 as snapshot_support

NOW = datetime(2026, 10, 12, 23, 5, tzinfo=UTC)


def _stored(family: str = "conventional"):
    content, _ = snapshot_support._available_preview_bytes(family)
    frozen = frozen_grade_report_preview_from_json_bytes(content)
    reference = ReportingSnapshotReference(
        class_id=snapshot_support.CLASS_ID,
        snapshot_id="snapshot_001",
        snapshot_sha256="f" * 64,
    )
    return reference, SimpleNamespace(
        reference=reference,
        snapshot=SimpleNamespace(report_preview=frozen, created_at=NOW),
    )


def test_historical_report_uses_frozen_row_without_current_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reference, stored = _stored("conventional")
    monkeypatch.setattr(
        justification, "load_reporting_snapshot", lambda *a, **k: stored
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("historical mode must not resolve current Grade")

    monkeypatch.setattr(justification, "explain_current_grade_preview", forbidden)

    report = build_snapshot_student_grade_justification(
        ".",
        reference,
        snapshot_support._target().student_id,
        generated_at=NOW,
    )

    kinds = {item.source_kind for item in report.source_references}
    assert {"reporting_snapshot", "grade_observation", "grade_explanation"} <= kinds
    assert any(
        diagnostic.code == "report.historical_snapshot"
        for diagnostic in report.diagnostics
    )


def test_historical_multiple_family_rows_require_explicit_family(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conventional, _ = snapshot_support._available_preview_bytes("conventional")
    standards, _ = snapshot_support._available_preview_bytes("standards_based")
    one = frozen_grade_report_preview_from_json_bytes(conventional)
    two = frozen_grade_report_preview_from_json_bytes(standards)
    reference = ReportingSnapshotReference(
        class_id=snapshot_support.CLASS_ID,
        snapshot_id="snapshot_multi",
        snapshot_sha256="e" * 64,
    )
    stored = SimpleNamespace(
        reference=reference,
        snapshot=SimpleNamespace(
            report_preview=SimpleNamespace(rows=(one.rows[0], two.rows[0])),
            created_at=NOW,
        ),
    )
    monkeypatch.setattr(
        justification, "load_reporting_snapshot", lambda *a, **k: stored
    )

    with pytest.raises(StudentGradeJustificationAmbiguousError):
        build_snapshot_student_grade_justification(
            ".",
            reference,
            snapshot_support._target().student_id,
            generated_at=NOW,
        )
