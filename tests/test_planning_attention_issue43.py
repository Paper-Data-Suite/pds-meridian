from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pds_core.module_operations import ModuleOperationsRequest

import meridian.planning_attention as planning_attention
from meridian.attention_provider import evaluate_meridian_attention
from meridian.planning_attention import (
    PlanningAttentionCurrentness,
    PlanningAttentionIntegrityError,
    PlanningAttentionReviewState,
    PlanningAttentionScopeState,
    build_planning_attention_summary,
    inspect_planning_attention_for_class,
)


def _state(
    policy: str,
    derivation: str,
    currentness: PlanningAttentionCurrentness,
    review_state: PlanningAttentionReviewState,
) -> PlanningAttentionScopeState:
    return PlanningAttentionScopeState(
        policy_id=policy,
        derivation_id=derivation,
        currentness=currentness,
        review_state=review_state,
    )


def test_current_preview_without_review_is_pending() -> None:
    summary = build_planning_attention_summary(
        (_state("policy-a", "derivation-a", "current", "none"),),
        "class-01",
    )
    assert [(item.code, item.count) for item in summary.items] == [
        ("meridian_planning_review_pending", 1)
    ]


def test_unselected_review_history_is_selection_pending() -> None:
    summary = build_planning_attention_summary(
        (
            _state(
                "policy-a",
                "derivation-a",
                "current",
                "unselected_history",
            ),
        ),
        "class-01",
    )
    assert [(item.code, item.count) for item in summary.items] == [
        ("meridian_planning_review_selection_pending", 1)
    ]


@pytest.mark.parametrize(
    "review_state",
    ["selected_current", "selected_rejected"],
)
def test_current_selected_review_is_resolved(
    review_state: PlanningAttentionReviewState,
) -> None:
    summary = build_planning_attention_summary(
        (_state("policy-a", "derivation-a", "current", review_state),),
        "class-01",
    )
    assert summary.items == ()


def test_stale_selected_review_is_one_policy_scope() -> None:
    summary = build_planning_attention_summary(
        (
            _state("policy-a", "derivation-old-1", "stale", "selected_stale"),
            _state("policy-a", "derivation-old-2", "stale", "selected_stale"),
        ),
        "class-01",
    )
    assert [(item.code, item.count) for item in summary.items] == [
        ("meridian_planning_review_stale", 1)
    ]


def test_historical_unreviewed_preview_is_not_attention() -> None:
    summary = build_planning_attention_summary(
        (_state("policy-a", "derivation-old", "stale", "none"),),
        "class-01",
    )
    assert summary.items == ()


def test_current_scope_suppresses_historical_stale_noise() -> None:
    summary = build_planning_attention_summary(
        (
            _state("policy-a", "derivation-old", "stale", "selected_stale"),
            _state("policy-a", "derivation-current", "current", "selected_current"),
        ),
        "class-01",
    )
    assert summary.items == ()


def test_multiple_current_derivations_for_one_policy_are_integrity_failure() -> None:
    with pytest.raises(PlanningAttentionIntegrityError):
        build_planning_attention_summary(
            (
                _state("policy-a", "derivation-a", "current", "none"),
                _state("policy-a", "derivation-b", "current", "none"),
            ),
            "class-01",
        )


def test_planning_counts_are_by_policy_and_canonical_category_order() -> None:
    summary = build_planning_attention_summary(
        (
            _state("policy-a", "derivation-a", "current", "none"),
            _state("policy-b", "derivation-b", "current", "none"),
            _state("policy-c", "derivation-c", "current", "unselected_history"),
            _state("policy-d", "derivation-d", "stale", "selected_stale"),
        ),
        "class-01",
    )
    assert [(item.code, item.count) for item in summary.items] == [
        ("meridian_planning_review_pending", 2),
        ("meridian_planning_review_selection_pending", 1),
        ("meridian_planning_review_stale", 1),
    ]


def _preview(
    *,
    policy_id: str,
    derivation_id: str,
    school_year: str = "2026-2027",
) -> object:
    snapshot = SimpleNamespace(
        derivation_reference=SimpleNamespace(derivation_id=derivation_id),
        policy_reference=SimpleNamespace(policy_id=policy_id),
        academic_basis=SimpleNamespace(
            target_period=SimpleNamespace(
                period=SimpleNamespace(school_year=school_year)
            )
        ),
    )
    return SimpleNamespace(snapshot=snapshot)


def test_class_inspection_uses_current_pointer_and_school_year_filter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class_dir = tmp_path / "classes" / "class-01"
    class_dir.mkdir(parents=True)
    previews = {
        "preview-a": _preview(policy_id="policy-a", derivation_id="derivation-a"),
        "preview-b": _preview(
            policy_id="policy-b",
            derivation_id="derivation-b",
            school_year="2025-2026",
        ),
    }
    monkeypatch.setattr(
        planning_attention,
        "list_grouping_signal_preview_ids",
        lambda *_args: tuple(previews),
    )
    monkeypatch.setattr(
        planning_attention,
        "load_grouping_signal_preview",
        lambda _root, _class_id, preview_id: previews[preview_id],
    )
    monkeypatch.setattr(
        planning_attention,
        "assess_grouping_signal_derivation_currentness",
        lambda *_args: SimpleNamespace(state="current"),
    )
    monkeypatch.setattr(
        planning_attention,
        "load_current_grouping_signal_review",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        planning_attention,
        "list_grouping_signal_review_revisions",
        lambda *_args: (),
    )

    summary = inspect_planning_attention_for_class(
        tmp_path,
        "class-01",
        active_school_year="2026-2027",
    )
    assert [(item.code, item.count) for item in summary.items] == [
        ("meridian_planning_review_pending", 1)
    ]


def test_exact_class_provider_returns_evaluated_empty_without_planning_state(
    tmp_path: Path,
) -> None:
    (tmp_path / "classes" / "class-01").mkdir(parents=True)
    request = ModuleOperationsRequest(
        workspace_root=tmp_path.resolve(),
        class_id="class-01",
    )
    report = evaluate_meridian_attention(request)
    assert report.evaluation == "evaluated"
    assert report.summaries == ()
    assert report.notices == ()


def test_unknown_exact_class_is_unavailable(tmp_path: Path) -> None:
    request = ModuleOperationsRequest(
        workspace_root=tmp_path.resolve(),
        class_id="class-missing",
    )
    report = evaluate_meridian_attention(request)
    assert report.evaluation == "unavailable"
    assert report.summaries == ()
    assert [notice.code for notice in report.notices] == [
        "meridian_attention_unavailable"
    ]


def test_workspace_wide_provider_empty_workspace_is_evaluated(
    tmp_path: Path,
) -> None:
    report = evaluate_meridian_attention(
        ModuleOperationsRequest(workspace_root=tmp_path.resolve())
    )
    assert report.evaluation == "evaluated"
    assert report.summaries == ()
    assert report.notices == ()


def test_class_attention_evaluation_does_not_write(tmp_path: Path) -> None:
    class_dir = tmp_path / "classes" / "class-01"
    class_dir.mkdir(parents=True)
    before = tuple(
        sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    )
    evaluate_meridian_attention(
        ModuleOperationsRequest(
            workspace_root=tmp_path.resolve(),
            class_id="class-01",
        )
    )
    after = tuple(
        sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    )
    assert after == before
