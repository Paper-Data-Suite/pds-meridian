from __future__ import annotations

import pytest

from meridian.proficiency_attention import (
    MERIDIAN_ATTENTION_SCHEMA_VERSION,
    MeridianAttentionItem,
    MeridianAttentionValidationError,
    attention_definition,
    build_meridian_attention_summary,
    meridian_attention_definitions,
    meridian_attention_summary_to_dict,
)


def test_grade_report_attention_definitions_use_v03_menu_destinations() -> None:
    expected = {
        "meridian_grade_result_stale": (
            "grade_result_targets",
            "preview-grades",
            "open_preview_grades",
        ),
        "meridian_reporting_publication_changed": (
            "reporting_snapshot_scopes",
            "snapshots",
            "open_snapshots",
        ),
        "meridian_reporting_snapshot_refresh_needed": (
            "reporting_snapshot_scopes",
            "snapshots",
            "open_snapshots",
        ),
        "meridian_reporting_snapshot_selection_pending": (
            "reporting_snapshot_scopes",
            "snapshots",
            "open_snapshots",
        ),
    }

    for code, values in expected.items():
        definition = attention_definition(code)  # type: ignore[arg-type]
        assert (
            definition.count_unit,
            definition.destination_id,
            definition.action_id,
        ) == values
        assert definition.task_id is None


def test_grade_report_attention_order_precedes_planning_and_ignores_count() -> None:
    summary = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code="meridian_planning_review_pending",
                count=1,
            ),
            MeridianAttentionItem(
                code="meridian_reporting_snapshot_selection_pending",
                count=999,
            ),
            MeridianAttentionItem(
                code="meridian_reporting_publication_changed",
                count=2,
            ),
            MeridianAttentionItem(
                code="meridian_grade_result_stale",
                count=400,
            ),
            MeridianAttentionItem(
                code="meridian_academic_period_calculation_stale",
                count=5,
            ),
        )
    )

    assert tuple(item.code for item in summary.items) == (
        "meridian_academic_period_calculation_stale",
        "meridian_grade_result_stale",
        "meridian_reporting_publication_changed",
        "meridian_reporting_snapshot_selection_pending",
        "meridian_planning_review_pending",
    )


def test_native_json_v2_exposes_destination_without_fabricating_legacy_task() -> None:
    summary = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code="meridian_grade_result_stale",
                count=2,
                class_id="class-01",
            ),
            MeridianAttentionItem(
                code="meridian_reporting_snapshot_refresh_needed",
                count=1,
                class_id="class-01",
            ),
        )
    )

    payload = meridian_attention_summary_to_dict(summary)

    assert payload["schema_version"] == MERIDIAN_ATTENTION_SCHEMA_VERSION == 2
    assert payload["items"] == [
        {
            "code": "meridian_grade_result_stale",
            "label": "Selected Grade results need fresh preview review",
            "count": 2,
            "count_unit": "grade_result_targets",
            "destination_id": "preview-grades",
            "task_id": None,
            "action_id": "open_preview_grades",
            "class_id": "class-01",
        },
        {
            "code": "meridian_reporting_snapshot_refresh_needed",
            "label": "Current ReportingSnapshots need refresh review",
            "count": 1,
            "count_unit": "reporting_snapshot_scopes",
            "destination_id": "snapshots",
            "task_id": None,
            "action_id": "open_snapshots",
            "class_id": "class-01",
        },
    ]


def test_export_readiness_is_not_part_of_native_attention_vocabulary() -> None:
    codes = {definition.code for definition in meridian_attention_definitions()}

    assert "meridian_export_pending" not in codes
    assert "meridian_export_ready" not in codes
    assert "meridian_export_missing" not in codes

    for code in (
        "meridian_export_pending",
        "meridian_export_ready",
        "meridian_export_missing",
    ):
        with pytest.raises(MeridianAttentionValidationError):
            attention_definition(code)  # type: ignore[arg-type]
