from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.module_operations import ModuleOperationsRequest

import meridian.academic_period_attention as attention
import meridian.attention_provider as provider
import meridian.attention_service as service
from meridian.proficiency_attention import (
    MeridianAttentionItem,
    build_meridian_attention_summary,
)


def _pointer(
    path: Path,
    *,
    class_id: str,
    school_year: str,
    period_id: str,
    student_id: str,
    standard_id: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "record_type": "meridian_academic_period_proficiency_result_current",
                "class_id": class_id,
                "school_year": school_year,
                "period_id": period_id,
                "student_id": student_id,
                "standard_id": standard_id,
                "standard_key": path.parent.name,
                "result_revision": 1,
                "result_sha256": "a" * 64,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_missing_result_collection_is_not_attention(tmp_path: Path) -> None:
    summary = attention.inspect_academic_period_attention_for_class(
        tmp_path,
        "class-a",
    )
    assert summary.items == ()


def test_selected_stale_targets_are_aggregated_once_each(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class_id = "class-a"
    root = attention.academic_period_proficiency_results_directory(tmp_path, class_id)
    calls: list[str] = []

    for student in ("student-a", "student-b", "student-c"):
        path = (
            root
            / "school_years"
            / "2026-2027"
            / "periods"
            / "mp1"
            / "students"
            / student
            / "standards"
            / (student[-1] * 64)
            / "current.json"
        )
        _pointer(
            path,
            class_id=class_id,
            school_year="2026-2027",
            period_id="mp1",
            student_id=student,
            standard_id="NJSLSA.R1",
        )

    def fake_current(*args: object, **kwargs: object) -> object:
        student = str(args[4])
        return SimpleNamespace(snapshot=SimpleNamespace(student_id=student))

    def fake_stale(_root: object, stored: object) -> bool:
        student = str(stored.snapshot.student_id)
        calls.append(student)
        return student != "student-c"

    monkeypatch.setattr(
        attention,
        "load_current_academic_period_proficiency_result",
        fake_current,
    )
    monkeypatch.setattr(attention, "_current_result_is_stale", fake_stale)
    monkeypatch.setattr(
        attention,
        "academic_period_proficiency_result_current_path",
        lambda root, class_id, school_year, period_id, student_id, standard_id: (
            attention.academic_period_proficiency_results_directory(root, class_id)
            / "school_years"
            / school_year
            / "periods"
            / period_id
            / "students"
            / student_id
            / "standards"
            / (student_id[-1] * 64)
            / "current.json"
        ),
    )

    summary = attention.inspect_academic_period_attention_for_class(tmp_path, class_id)
    assert calls == ["student-a", "student-b", "student-c"]
    assert len(summary.items) == 1
    item = summary.items[0]
    assert item.code == "meridian_academic_period_calculation_stale"
    assert item.count == 2
    assert item.class_id == class_id
    assert item.definition.count_unit == "academic_period_proficiency_targets"


def test_school_year_filter_excludes_other_selected_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class_id = "class-a"
    root = attention.academic_period_proficiency_results_directory(tmp_path, class_id)
    paths: list[Path] = []
    for year in ("2025-2026", "2026-2027"):
        path = (
            root
            / "school_years"
            / year
            / "periods"
            / "mp1"
            / "students"
            / "student-a"
            / "standards"
            / ("a" * 64)
            / "current.json"
        )
        paths.append(path)
        _pointer(
            path,
            class_id=class_id,
            school_year=year,
            period_id="mp1",
            student_id="student-a",
            standard_id="NJSLSA.R1",
        )

    seen: list[str] = []

    def fake_current(*args: object, **kwargs: object) -> object:
        year = str(args[2])
        seen.append(year)
        return SimpleNamespace(snapshot=SimpleNamespace(student_id="student-a"))

    monkeypatch.setattr(
        attention,
        "load_current_academic_period_proficiency_result",
        fake_current,
    )
    monkeypatch.setattr(attention, "_current_result_is_stale", lambda *_: True)
    monkeypatch.setattr(
        attention,
        "academic_period_proficiency_result_current_path",
        lambda root, class_id, school_year, period_id, student_id, standard_id: (
            attention.academic_period_proficiency_results_directory(root, class_id)
            / "school_years"
            / school_year
            / "periods"
            / period_id
            / "students"
            / student_id
            / "standards"
            / ("a" * 64)
            / "current.json"
        ),
    )

    summary = attention.inspect_academic_period_attention_for_class(
        tmp_path,
        class_id,
        active_school_year="2026-2027",
    )
    assert seen == ["2026-2027"]
    assert summary.items[0].count == 1


def test_malformed_current_pointer_is_integrity_failure(tmp_path: Path) -> None:
    root = attention.academic_period_proficiency_results_directory(tmp_path, "class-a")
    path = root / "school_years" / "2026-2027" / "current.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(attention.AcademicPeriodAttentionReadError):
        attention.inspect_academic_period_attention_for_class(tmp_path, "class-a")


def test_provider_combines_planning_and_academic_period_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "classes" / "class-a").mkdir(parents=True)
    planning = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                "meridian_planning_review_pending",
                1,
                "class-a",
            ),
        )
    )
    period = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                "meridian_academic_period_calculation_stale",
                2,
                "class-a",
            ),
        )
    )
    monkeypatch.setattr(
        service,
        "inspect_planning_attention_for_class",
        lambda *args, **kwargs: planning,
    )
    monkeypatch.setattr(
        service,
        "inspect_academic_period_attention_for_class",
        lambda *args, **kwargs: period,
    )

    report = provider.evaluate_meridian_attention(
        ModuleOperationsRequest(
            workspace_root=tmp_path.resolve(),
            class_id="class-a",
        )
    )
    assert report.evaluation == "evaluated"
    assert [item.code for item in report.summaries] == [
        "meridian_academic_period_calculation_stale",
        "meridian_planning_review_pending",
    ]
    assert [item.count for item in report.summaries] == [2, 1]


def test_provider_fails_closed_when_academic_period_attention_is_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "classes" / "class-a").mkdir(parents=True)
    monkeypatch.setattr(
        service,
        "inspect_planning_attention_for_class",
        lambda *args, **kwargs: build_meridian_attention_summary(()),
    )

    def fail(*args: object, **kwargs: object) -> object:
        raise attention.AcademicPeriodAttentionReadError("private detail")

    monkeypatch.setattr(
        service,
        "inspect_academic_period_attention_for_class",
        fail,
    )
    report = provider.evaluate_meridian_attention(
        ModuleOperationsRequest(
            workspace_root=tmp_path.resolve(),
            class_id="class-a",
        )
    )
    assert report.evaluation == "unavailable"
    assert report.summaries == ()
    assert "private detail" not in report.notices[0].summary
