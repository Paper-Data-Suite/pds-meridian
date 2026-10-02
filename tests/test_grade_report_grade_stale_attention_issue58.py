from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.academic_periods import AcademicPeriodRef

import meridian.grade_report_attention as attention
from meridian.grade_report_attention import (
    GradeReportAttentionReadError,
    inspect_grade_report_attention_for_class,
)
from meridian.standards_grade_storage import (
    STANDARDS_GRADE_RESULT_CURRENT_RECORD_TYPE,
    STANDARDS_GRADE_RESULT_CURRENT_SCHEMA_VERSION,
    standards_grade_result_current_path,
    standards_grade_subject_key,
)

CLASS_ID = "english_12"
PERIOD = AcademicPeriodRef("2026-2027", "q1")


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / "classes" / CLASS_ID).mkdir(parents=True)
    return root


def _stored(student_id: str = "student_001", *, reference: object | None = None):
    return SimpleNamespace(
        snapshot=SimpleNamespace(
            class_id=CLASS_ID,
            student_id=student_id,
            target_period=PERIOD,
            calendar_revision=1,
        ),
        reference=object() if reference is None else reference,
    )


def _install_no_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(attention, "list_reporting_snapshot_ids", lambda *args: ())


def test_selected_stale_standards_grade_emits_preview_grades_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    stored = _stored()
    _install_no_snapshots(monkeypatch)
    monkeypatch.setattr(
        attention,
        "_discover_current_standards_grade_results",
        lambda *args, **kwargs: (stored,),
    )
    monkeypatch.setattr(
        attention,
        "assemble_standards_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(inputs=object()),
    )
    monkeypatch.setattr(
        attention,
        "assess_standards_grade_result_freshness",
        lambda *args, **kwargs: SimpleNamespace(
            status="stale", reasons=("policy_changed",)
        ),
    )
    monkeypatch.setattr(
        attention,
        "load_current_standards_grade_result",
        lambda *args, **kwargs: stored,
    )

    summary = inspect_grade_report_attention_for_class(root, CLASS_ID)

    assert len(summary.items) == 1
    item = summary.items[0]
    assert item.code == "meridian_grade_result_stale"
    assert item.count == 1
    assert item.class_id == CLASS_ID
    assert item.definition.destination_id == "preview-grades"
    assert item.definition.action_id == "open_preview_grades"


def test_selected_current_standards_grade_is_not_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    stored = _stored()
    _install_no_snapshots(monkeypatch)
    monkeypatch.setattr(
        attention,
        "_discover_current_standards_grade_results",
        lambda *args, **kwargs: (stored,),
    )
    monkeypatch.setattr(
        attention,
        "assemble_standards_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(inputs=object()),
    )
    monkeypatch.setattr(
        attention,
        "assess_standards_grade_result_freshness",
        lambda *args, **kwargs: SimpleNamespace(status="current", reasons=()),
    )
    monkeypatch.setattr(
        attention,
        "load_current_standards_grade_result",
        lambda *args, **kwargs: stored,
    )

    summary = inspect_grade_report_attention_for_class(root, CLASS_ID)

    assert summary.items == ()


def test_stale_grade_attention_counts_targets_not_staleness_reasons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    first = _stored("student_001")
    second = _stored("student_002")
    current = {
        "student_001": first,
        "student_002": second,
    }
    _install_no_snapshots(monkeypatch)
    monkeypatch.setattr(
        attention,
        "_discover_current_standards_grade_results",
        lambda *args, **kwargs: (first, second),
    )
    monkeypatch.setattr(
        attention,
        "assemble_standards_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(inputs=object()),
    )
    monkeypatch.setattr(
        attention,
        "assess_standards_grade_result_freshness",
        lambda *args, **kwargs: SimpleNamespace(
            status="stale",
            reasons=("activation_changed", "policy_changed", "algorithm_changed"),
        ),
    )
    monkeypatch.setattr(
        attention,
        "load_current_standards_grade_result",
        lambda _root, _class, student, *_args: current[student],
    )

    summary = inspect_grade_report_attention_for_class(root, CLASS_ID)

    assert tuple((item.code, item.count) for item in summary.items) == (
        ("meridian_grade_result_stale", 2),
    )


def test_selector_movement_after_freshness_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    original = _stored(reference="selected-a")
    moved = _stored(reference="selected-b")
    _install_no_snapshots(monkeypatch)
    monkeypatch.setattr(
        attention,
        "_discover_current_standards_grade_results",
        lambda *args, **kwargs: (original,),
    )
    monkeypatch.setattr(
        attention,
        "assemble_standards_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(inputs=object()),
    )
    monkeypatch.setattr(
        attention,
        "assess_standards_grade_result_freshness",
        lambda *args, **kwargs: SimpleNamespace(status="stale", reasons=()),
    )
    monkeypatch.setattr(
        attention,
        "load_current_standards_grade_result",
        lambda *args, **kwargs: moved,
    )

    with pytest.raises(GradeReportAttentionReadError, match="selection changed"):
        inspect_grade_report_attention_for_class(root, CLASS_ID)


def test_final_stale_selector_revalidation_rejects_late_movement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    original = _stored(reference="selected-a")
    moved = _stored(reference="selected-b")
    reads = iter((original, original, moved))
    _install_no_snapshots(monkeypatch)
    monkeypatch.setattr(
        attention,
        "_discover_current_standards_grade_results",
        lambda *args, **kwargs: (original,),
    )
    monkeypatch.setattr(
        attention,
        "assemble_standards_grade_calculation",
        lambda *args, **kwargs: SimpleNamespace(inputs=object()),
    )
    monkeypatch.setattr(
        attention,
        "assess_standards_grade_result_freshness",
        lambda *args, **kwargs: SimpleNamespace(status="stale", reasons=()),
    )

    def load_current(*args, **kwargs):
        return next(reads)

    monkeypatch.setattr(attention, "load_current_standards_grade_result", load_current)

    with pytest.raises(GradeReportAttentionReadError, match="selection changed"):
        inspect_grade_report_attention_for_class(root, CLASS_ID)


def _write_pointer(root: Path, *, school_year: str, student_id: str) -> Path:
    period = AcademicPeriodRef(school_year, "q1")
    path = standards_grade_result_current_path(
        root,
        CLASS_ID,
        student_id,
        period,
        1,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "schema_version": STANDARDS_GRADE_RESULT_CURRENT_SCHEMA_VERSION,
        "record_type": STANDARDS_GRADE_RESULT_CURRENT_RECORD_TYPE,
        "class_id": CLASS_ID,
        "student_id": student_id,
        "school_year": school_year,
        "period_id": "q1",
        "calendar_revision": 1,
        "subject_key": standards_grade_subject_key(
            CLASS_ID, student_id, period, 1
        ),
        "result_revision": 1,
        "result_sha256": "a" * 64,
    }
    path.write_text(
        json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def test_canonical_pointer_discovery_uses_public_selected_result_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    stored = _stored()
    _write_pointer(root, school_year="2026-2027", student_id="student_001")
    calls: list[tuple[str, str, str, int]] = []

    def load_current(_root, class_id, student_id, period, calendar_revision):
        calls.append(
            (class_id, student_id, period.school_year, calendar_revision)
        )
        return stored

    monkeypatch.setattr(attention, "load_current_standards_grade_result", load_current)

    discovered = attention._discover_current_standards_grade_results(
        root,
        CLASS_ID,
        active_school_year="2026-2027",
    )

    assert discovered == (stored,)
    assert calls == [(CLASS_ID, "student_001", "2026-2027", 1)]


def test_school_year_filter_does_not_open_out_of_scope_selected_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _workspace(tmp_path)
    _write_pointer(root, school_year="2025-2026", student_id="student_001")

    def forbidden(*args, **kwargs):
        raise AssertionError("out-of-scope selected result must not be opened")

    monkeypatch.setattr(attention, "load_current_standards_grade_result", forbidden)

    discovered = attention._discover_current_standards_grade_results(
        root,
        CLASS_ID,
        active_school_year="2026-2027",
    )

    assert discovered == ()


def test_malformed_selected_pointer_is_operational_failure(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    path = (
        root
        / "classes"
        / CLASS_ID
        / "modules"
        / "meridian"
        / "standards_grades"
        / "periods"
        / "2026-2027"
        / "q1"
        / "students"
        / ("a" * 64)
        / "current.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text('{"not":"a current pointer"}\n', encoding="utf-8")

    with pytest.raises(GradeReportAttentionReadError, match="shape is invalid"):
        attention._discover_current_standards_grade_results(
            root,
            CLASS_ID,
            active_school_year=None,
        )
