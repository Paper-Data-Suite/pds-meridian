from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.attention_service as attention_service
from meridian.grade_preview_explanation import GradePreviewTarget
from meridian.grade_report_attention import (
    GradeReportAttentionReadError,
    inspect_grade_report_attention_for_class,
)
from meridian.proficiency_attention import (
    MeridianAttentionItem,
    build_meridian_attention_summary,
)
from meridian.reporting_snapshot import (
    REPORTING_DEFINITION_RECORD_TYPE,
    REPORTING_DEFINITION_SCHEMA_VERSION,
    ReportingActor,
    ReportingDefinitionRevision,
    ReportingSnapshotPredecessor,
)
from meridian.reporting_snapshot_preview import (
    frozen_grade_report_preview_from_json_bytes,
)
from meridian.reporting_snapshot_record import (
    REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
    ReportingSnapshotBuildRequest,
    ReportingSnapshotGradeRequest,
    compose_reporting_snapshot,
    reporting_snapshot_provenance_binding,
)
from meridian.reporting_snapshot_selection import select_reporting_snapshot
from meridian.reporting_snapshot_storage import (
    reporting_snapshot_digest_path,
    write_reporting_definition_revision,
    write_reporting_snapshot,
)

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    return root


def _definition() -> ReportingDefinitionRevision:
    return ReportingDefinitionRevision(
        schema_version=REPORTING_DEFINITION_SCHEMA_VERSION,
        record_type=REPORTING_DEFINITION_RECORD_TYPE,
        class_id=CLASS_ID,
        definition_id="quarter_grade_report",
        definition_revision=1,
        supersedes_revision=None,
        report_kind="grade_report",
        purpose="quarter_grade_review",
        title="Quarter Grade Report",
        target_period=PERIOD,
        intended_audience="teacher",
        actor=ReportingActor("teacher", "teacher_local"),
        rationale=None,
        revised_at=NOW,
    )


def _target() -> GradePreviewTarget:
    return GradePreviewTarget(
        class_id=CLASS_ID,
        student_id="student_001",
        target_period=PERIOD,
        calendar_revision=1,
        calculation_family="standards_based",
    )


def _preview(target: GradePreviewTarget):
    data = {
        "summary": {
            "requested_count": 1,
            "available_count": 0,
            "unavailable_count": 1,
            "base_calculated_count": 0,
            "base_blocked_count": 0,
            "base_insufficient_count": 0,
            "current_count": 0,
            "stale_count": 0,
            "effective_numeric_count": 0,
            "effective_nonnumeric_count": 0,
            "effective_base_count": 0,
            "effective_override_count": 0,
            "effective_none_count": 0,
        },
        "rows": [
            {
                "target": {
                    "class_id": target.class_id,
                    "student_id": target.student_id,
                    "target_period": {
                        "school_year": target.target_period.school_year,
                        "period_id": target.target_period.period_id,
                    },
                    "calendar_revision": target.calendar_revision,
                    "calculation_family": target.calculation_family,
                },
                "status": "unavailable",
                "unavailable_reason": "no_selected_grade",
                "explanation": None,
                "observation": None,
            }
        ],
    }
    encoded = (
        json.dumps(
            data,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return frozen_grade_report_preview_from_json_bytes(encoded)


def _snapshot(
    definition_reference,
    *,
    snapshot_id: str,
    minute: int,
    predecessor: ReportingSnapshotPredecessor | None = None,
):
    target = _target()
    request = ReportingSnapshotBuildRequest(
        schema_version=REPORTING_SNAPSHOT_BUILD_REQUEST_SCHEMA_VERSION,
        definition_reference=definition_reference,
        grade_requests=(
            ReportingSnapshotGradeRequest(target=target, work_evidence=None),
        ),
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Freeze reviewed report.",
        requested_at=NOW,
        predecessor=predecessor,
    )
    return compose_reporting_snapshot(
        snapshot_id=snapshot_id,
        build_request=request,
        report_preview=_preview(target),
        provenance_bindings=(
            reporting_snapshot_provenance_binding(
                authority_kind="academic_period_calendar",
                reference_kind="academic_period_calendar_reference",
                reference={
                    "school_year": PERIOD.school_year,
                    "calendar_revision": 1,
                },
            ),
        ),
        created_at=NOW + timedelta(minutes=minute),
    )


def _setup(
    tmp_path: Path,
    *,
    relationship: str = "replaces_for_current_use",
):
    root = _workspace(tmp_path)
    definition = write_reporting_definition_revision(root, _definition()).stored
    first = write_reporting_snapshot(
        root,
        _snapshot(definition.reference, snapshot_id="snapshot_a", minute=0),
    ).stored
    predecessor = ReportingSnapshotPredecessor(
        relationship=relationship,  # type: ignore[arg-type]
        snapshot_reference=first.reference,
    )
    second = write_reporting_snapshot(
        root,
        _snapshot(
            definition.reference,
            snapshot_id="snapshot_b",
            minute=5,
            predecessor=predecessor,
        ),
    ).stored
    return root, first, second


def _select(root: Path, snapshot, expected, minute: int):
    return select_reporting_snapshot(
        root,
        snapshot.reference,
        actor=ReportingActor("teacher", "teacher_local"),
        rationale="Use this frozen report.",
        decided_at=NOW + timedelta(minutes=minute),
        expected_current=expected,
    )


def test_explicit_replacement_with_predecessor_selected_is_attention(
    tmp_path: Path,
) -> None:
    root, predecessor, _ = _setup(tmp_path)
    _select(root, predecessor, None, 10)

    summary = inspect_grade_report_attention_for_class(root, CLASS_ID)

    assert summary.items == (
        MeridianAttentionItem(
            code="meridian_reporting_snapshot_selection_pending",
            count=1,
            class_id=CLASS_ID,
        ),
    )


def test_replacement_attention_disappears_when_successor_is_selected(
    tmp_path: Path,
) -> None:
    root, predecessor, successor = _setup(tmp_path)
    first = _select(root, predecessor, None, 10)
    _select(root, successor, first.selection.reference, 15)

    summary = inspect_grade_report_attention_for_class(root, CLASS_ID)

    assert summary.items == ()


def test_absent_selection_and_nonreplacement_do_not_infer_attention(
    tmp_path: Path,
) -> None:
    root, _, _ = _setup(tmp_path, relationship="supersedes")

    summary = inspect_grade_report_attention_for_class(root, CLASS_ID)

    assert summary.items == ()


def test_newer_unrelated_snapshot_does_not_create_selection_attention(
    tmp_path: Path,
) -> None:
    root, predecessor, _ = _setup(tmp_path, relationship="supersedes")
    _select(root, predecessor, None, 10)

    summary = inspect_grade_report_attention_for_class(root, CLASS_ID)

    assert summary.items == ()


def test_active_school_year_filters_replacement_attention(tmp_path: Path) -> None:
    root, predecessor, _ = _setup(tmp_path)
    _select(root, predecessor, None, 10)

    assert inspect_grade_report_attention_for_class(
        root,
        CLASS_ID,
        active_school_year="2025-2026",
    ).items == ()
    assert len(
        inspect_grade_report_attention_for_class(
            root,
            CLASS_ID,
            active_school_year="2026-2027",
        ).items
    ) == 1


def test_corrupt_reporting_state_fails_closed(tmp_path: Path) -> None:
    root, predecessor, successor = _setup(tmp_path)
    _select(root, predecessor, None, 10)
    reporting_snapshot_digest_path(
        root,
        CLASS_ID,
        successor.snapshot.snapshot_id,
    ).write_text("f" * 64 + "\n", encoding="ascii")

    with pytest.raises(GradeReportAttentionReadError):
        inspect_grade_report_attention_for_class(root, CLASS_ID)


def test_attention_service_composes_grade_report_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    empty = build_meridian_attention_summary(())
    grade_report = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code="meridian_reporting_snapshot_selection_pending",
                count=2,
                class_id=CLASS_ID,
            ),
        )
    )
    seen: list[str | None] = []

    monkeypatch.setattr(
        attention_service,
        "inspect_planning_attention_for_class",
        lambda *args, **kwargs: empty,
    )
    monkeypatch.setattr(
        attention_service,
        "inspect_academic_period_attention_for_class",
        lambda *args, **kwargs: empty,
    )

    def grade_report_inspector(*args, active_school_year=None, **kwargs):
        seen.append(active_school_year)
        return grade_report

    monkeypatch.setattr(
        attention_service,
        "inspect_grade_report_attention_for_class",
        grade_report_inspector,
    )

    result = attention_service.inspect_meridian_attention(
        root,
        class_id=CLASS_ID,
        active_school_year="2026-2027",
    )

    assert result.summary == grade_report
    assert seen == ["2026-2027"]
