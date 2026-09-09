from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path
from typing import get_args

import pytest

import meridian
from meridian.academic_period_proficiency_explanation import (
    AcademicPeriodProficiencyTargetSelection,
)
from meridian.grade_item_proficiency_explanation import (
    GradeItemProficiencyTargetSelection,
)
from meridian.planning_attention import (
    PlanningAttentionIntegrityError,
    PlanningAttentionScopeState,
    build_planning_attention_summary,
)
from meridian.planning_signal_derivation_explanation import (
    PlanningSignalDerivationTraceTarget,
)
from meridian.planning_signal_export_explanation import (
    PlanningSignalExportTraceTarget,
)
from meridian.proficiency_attention import MeridianAttentionItem

ATTENTION_MODULES = (
    "academic_period_attention.py",
    "planning_attention.py",
    "attention_service.py",
)


def _package_root() -> Path:
    assert meridian.__file__ is not None
    return Path(meridian.__file__).resolve().parent


def _tree(filename: str) -> ast.Module:
    path = _package_root() / filename
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _selection_literals(
    filename: str,
    constructor_name: str,
) -> tuple[str, ...]:
    values: list[str] = []
    for node in ast.walk(_tree(filename)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Name) or func.id != constructor_name:
            continue
        for keyword in node.keywords:
            if keyword.arg != "selection":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(
                keyword.value.value,
                str,
            ):
                values.append(keyword.value.value)
            else:
                values.append("<dynamic>")
    return tuple(values)


def test_proficiency_explanation_targets_keep_current_and_revision_explicit() -> None:
    assert get_args(GradeItemProficiencyTargetSelection) == (
        "current",
        "revision",
    )
    assert get_args(AcademicPeriodProficiencyTargetSelection) == (
        "current",
        "revision",
    )


def test_nested_explanations_follow_exact_historical_references() -> None:
    grade_item_nested = _selection_literals(
        "academic_period_proficiency_explanation.py",
        "GradeItemProficiencyTraceTarget",
    )
    period_nested = _selection_literals(
        "planning_signal_derivation_explanation.py",
        "AcademicPeriodProficiencyTraceTarget",
    )

    assert grade_item_nested
    assert period_nested
    assert set(grade_item_nested) == {"revision"}
    assert set(period_nested) == {"revision"}


def test_planning_explanations_have_exact_identity_targets_not_current_aliases(
) -> None:
    derivation_fields = tuple(
        field.name for field in fields(PlanningSignalDerivationTraceTarget)
    )
    assert derivation_fields == (
        "class_id",
        "derivation_id",
    )
    assert tuple(field.name for field in fields(PlanningSignalExportTraceTarget)) == (
        "class_id",
        "signal_set_id",
    )


def test_planning_attention_separates_current_review_from_historical_state() -> None:
    summary = build_planning_attention_summary(
        (
            PlanningAttentionScopeState(
                policy_id="policy-a",
                derivation_id="derivation-current",
                currentness="current",
                review_state="unselected_history",
            ),
            PlanningAttentionScopeState(
                policy_id="policy-b",
                derivation_id="derivation-stale",
                currentness="stale",
                review_state="selected_stale",
            ),
            PlanningAttentionScopeState(
                policy_id="policy-c",
                derivation_id="derivation-history-only",
                currentness="stale",
                review_state="unselected_history",
            ),
        ),
        "class-a",
    )

    by_code = {item.code: item.count for item in summary.items}
    assert by_code == {
        "meridian_planning_review_selection_pending": 1,
        "meridian_planning_review_stale": 1,
    }


def test_planning_attention_rejects_impossible_currentness_review_combinations(
) -> None:
    with pytest.raises(PlanningAttentionIntegrityError):
        PlanningAttentionScopeState(
            policy_id="policy-a",
            derivation_id="derivation-a",
            currentness="current",
            review_state="selected_stale",
        )
    with pytest.raises(PlanningAttentionIntegrityError):
        PlanningAttentionScopeState(
            policy_id="policy-a",
            derivation_id="derivation-b",
            currentness="stale",
            review_state="selected_current",
        )


def test_attention_payload_remains_aggregate_and_student_free() -> None:
    assert tuple(field.name for field in fields(MeridianAttentionItem)) == (
        "code",
        "count",
        "class_id",
    )


def test_attention_runtime_does_not_infer_active_school_year_from_clock() -> None:
    forbidden = (
        "date.today(",
        "datetime.today(",
        "datetime.now(",
    )

    for filename in ATTENTION_MODULES:
        source = (_package_root() / filename).read_text(encoding="utf-8")
        assert all(token not in source for token in forbidden)
