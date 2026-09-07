from __future__ import annotations

from pathlib import Path

import pytest
from pds_core.module_operations import ModuleOperationsRequest

import meridian.attention_provider as provider
import meridian.attention_service as service
from meridian.attention_service import (
    MeridianAttentionInspection,
    MeridianAttentionReadError,
    inspect_meridian_attention,
)
from meridian.planning_attention import PlanningAttentionReadError
from meridian.proficiency_attention import (
    MeridianAttentionCode,
    MeridianAttentionItem,
    build_meridian_attention_summary,
    merge_meridian_attention_summaries,
)


def _class(workspace: Path, class_id: str) -> None:
    (workspace / "classes" / class_id).mkdir(parents=True)


def _summary(code: MeridianAttentionCode, count: int, class_id: str):
    return build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code=code,
                count=count,
                class_id=class_id,
            ),
        )
    )


def test_native_merge_sums_same_code_and_elides_cross_class_context() -> None:
    merged = merge_meridian_attention_summaries(
        (
            _summary("meridian_planning_review_pending", 2, "class-a"),
            _summary("meridian_planning_review_pending", 3, "class-b"),
        )
    )

    assert len(merged.items) == 1
    item = merged.items[0]
    assert item.code == "meridian_planning_review_pending"
    assert item.count == 5
    assert item.class_id is None


def test_native_merge_retains_single_contributing_class_context() -> None:
    merged = merge_meridian_attention_summaries(
        (
            _summary("meridian_planning_review_pending", 2, "class-a"),
            _summary("meridian_academic_period_calculation_stale", 1, "class-b"),
        )
    )

    by_code = {item.code: item for item in merged.items}
    assert by_code["meridian_planning_review_pending"].class_id == "class-a"
    assert (
        by_code["meridian_academic_period_calculation_stale"].class_id
        == "class-b"
    )


def test_exact_class_inspection_requires_real_class_and_merges_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _class(tmp_path, "class-a")
    monkeypatch.setattr(
        service,
        "inspect_planning_attention_for_class",
        lambda *args, **kwargs: _summary(
            "meridian_planning_review_pending", 1, "class-a"
        ),
    )
    monkeypatch.setattr(
        service,
        "inspect_academic_period_attention_for_class",
        lambda *args, **kwargs: _summary(
            "meridian_academic_period_calculation_stale", 2, "class-a"
        ),
    )

    result = inspect_meridian_attention(tmp_path, class_id="class-a")

    assert result.partial is False
    assert result.evaluated_class_count == 1
    assert result.failed_scope_count == 0
    assert tuple(item.count for item in result.summary.items) == (2, 1)


def test_exact_unknown_class_is_unavailable_native_scope(tmp_path: Path) -> None:
    with pytest.raises(MeridianAttentionReadError):
        inspect_meridian_attention(tmp_path, class_id="missing-class")


def test_workspace_empty_is_successful_empty(tmp_path: Path) -> None:
    result = inspect_meridian_attention(tmp_path)

    assert result == MeridianAttentionInspection(
        summary=build_meridian_attention_summary(()),
        partial=False,
        evaluated_class_count=0,
        failed_scope_count=0,
    )


def test_workspace_partial_preserves_good_class_and_counts_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _class(tmp_path, "class-a")
    _class(tmp_path, "class-b")

    def planning(
        workspace_root: Path,
        class_id: str,
        *,
        active_school_year: str | None = None,
    ):
        if class_id == "class-b":
            raise PlanningAttentionReadError("synthetic failure")
        return _summary("meridian_planning_review_pending", 4, class_id)

    monkeypatch.setattr(service, "inspect_planning_attention_for_class", planning)
    monkeypatch.setattr(
        service,
        "inspect_academic_period_attention_for_class",
        lambda *args, **kwargs: build_meridian_attention_summary(()),
    )

    result = inspect_meridian_attention(tmp_path)

    assert result.partial is True
    assert result.evaluated_class_count == 1
    assert result.failed_scope_count == 1
    assert result.summary.items[0].class_id == "class-a"
    assert result.summary.items[0].count == 4


def test_workspace_all_class_failures_are_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _class(tmp_path, "class-a")
    def fail_planning(*args, **kwargs):
        raise PlanningAttentionReadError("synthetic failure")

    monkeypatch.setattr(
        service,
        "inspect_planning_attention_for_class",
        fail_planning,
    )

    with pytest.raises(MeridianAttentionReadError):
        inspect_meridian_attention(tmp_path)


def test_workspace_invalid_visible_entry_makes_success_partial(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _class(tmp_path, "class-a")
    (tmp_path / "classes" / "not-a-class.txt").write_text(
        "unexpected",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        service,
        "inspect_planning_attention_for_class",
        lambda *args, **kwargs: build_meridian_attention_summary(()),
    )
    monkeypatch.setattr(
        service,
        "inspect_academic_period_attention_for_class",
        lambda *args, **kwargs: build_meridian_attention_summary(()),
    )

    result = inspect_meridian_attention(tmp_path)

    assert result.partial is True
    assert result.evaluated_class_count == 1
    assert result.failed_scope_count == 1
    assert result.summary.items == ()


def test_active_school_year_is_forwarded_without_date_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _class(tmp_path, "class-a")
    seen: list[str | None] = []

    def capture(*args, active_school_year=None, **kwargs):
        seen.append(active_school_year)
        return build_meridian_attention_summary(())

    monkeypatch.setattr(service, "inspect_planning_attention_for_class", capture)
    monkeypatch.setattr(
        service,
        "inspect_academic_period_attention_for_class",
        capture,
    )

    inspect_meridian_attention(
        tmp_path,
        class_id="class-a",
        active_school_year="2026-2027",
    )

    assert seen == ["2026-2027", "2026-2027"]


def test_core_provider_workspace_partial_projects_bounded_notice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inspection = MeridianAttentionInspection(
        summary=_summary(
            "meridian_academic_period_calculation_stale",
            2,
            "class-a",
        ),
        partial=True,
        evaluated_class_count=1,
        failed_scope_count=1,
    )
    monkeypatch.setattr(
        provider,
        "inspect_meridian_attention",
        lambda *args, **kwargs: inspection,
    )

    report = provider.evaluate_meridian_attention(
        ModuleOperationsRequest(workspace_root=tmp_path.resolve())
    )

    assert report.evaluation == "evaluated"
    assert len(report.summaries) == 1
    assert tuple(notice.code for notice in report.notices) == (
        provider.MERIDIAN_ATTENTION_PARTIAL_NOTICE_CODE,
    )


def test_core_provider_unknown_exact_class_is_unavailable(tmp_path: Path) -> None:
    report = provider.evaluate_meridian_attention(
        ModuleOperationsRequest(
            workspace_root=tmp_path.resolve(),
            class_id="missing-class",
        )
    )

    assert report.evaluation == "unavailable"
    assert report.summaries == ()
    assert tuple(notice.code for notice in report.notices) == (
        provider.MERIDIAN_ATTENTION_UNAVAILABLE_NOTICE_CODE,
    )
