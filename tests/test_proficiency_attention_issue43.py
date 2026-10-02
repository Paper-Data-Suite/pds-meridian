from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from meridian.proficiency_attention import (
    MAX_MERIDIAN_ATTENTION_COUNT,
    MERIDIAN_ATTENTION_DESTINATION_IDS,
    MeridianAttentionItem,
    MeridianAttentionSummary,
    MeridianAttentionValidationError,
    attention_definition,
    build_meridian_attention_summary,
    meridian_attention_definitions,
    meridian_attention_summary_to_dict,
)


def test_attention_vocabulary_is_stable_and_follows_destination_order() -> None:
    definitions = meridian_attention_definitions()

    assert tuple(definition.code for definition in definitions) == (
        "meridian_evidence_review_pending",
        "meridian_membership_review_pending",
        "meridian_attempt_decision_pending",
        "meridian_contract_unsupported",
        "meridian_source_withdrawn",
        "meridian_source_superseded",
        "meridian_native_value_unmapped",
        "meridian_grade_item_calculation_stale",
        "meridian_academic_period_calculation_stale",
        "meridian_grade_result_stale",
        "meridian_reporting_publication_changed",
        "meridian_reporting_snapshot_refresh_needed",
        "meridian_reporting_snapshot_selection_pending",
        "meridian_planning_review_pending",
        "meridian_planning_review_selection_pending",
        "meridian_planning_review_stale",
    )
    destination_rank = {
        destination_id: index
        for index, destination_id in enumerate(MERIDIAN_ATTENTION_DESTINATION_IDS)
    }
    ranks = tuple(
        destination_rank[definition.destination_id] for definition in definitions
    )
    assert ranks == tuple(sorted(ranks))
    assert len({definition.code for definition in definitions}) == len(definitions)
    assert "meridian_export_pending" not in {
        definition.code for definition in definitions
    }
    assert "meridian_export_ready" not in {
        definition.code for definition in definitions
    }


def test_attention_definitions_fix_count_units_and_owner_actions() -> None:
    expected = {
        "meridian_evidence_review_pending": (
            "work_review_scopes",
            "new-evidence",
            "open_new_evidence",
        ),
        "meridian_membership_review_pending": (
            "membership_review_scopes",
            "grade-items",
            "open_grade_items",
        ),
        "meridian_attempt_decision_pending": (
            "attempt_decision_scopes",
            "attempt-decisions",
            "open_attempt_decisions",
        ),
        "meridian_contract_unsupported": (
            "evidence_review_scopes",
            "exclusions",
            "open_exclusions",
        ),
        "meridian_native_value_unmapped": (
            "mapping_inputs",
            "standards-review",
            "open_standards_review",
        ),
        "meridian_grade_item_calculation_stale": (
            "grade_item_proficiency_targets",
            "calculation-preview",
            "open_calculation_preview",
        ),
        "meridian_planning_review_pending": (
            "planning_review_scopes",
            "create-planning-signal",
            "open_create_planning_signal",
        ),
    }

    for code, values in expected.items():
        definition = attention_definition(code)  # type: ignore[arg-type]
        assert (
            definition.count_unit,
            definition.destination_id,
            definition.action_id,
        ) == values
        assert definition.task_id == definition.destination_id


def test_attention_item_is_frozen_and_validates_count_and_class_id() -> None:
    item = MeridianAttentionItem(
        code="meridian_attempt_decision_pending",
        count=2,
        class_id="class-01",
    )

    with pytest.raises(FrozenInstanceError):
        item.count = 3  # type: ignore[misc]

    for invalid in (True, 0, -1, MAX_MERIDIAN_ATTENTION_COUNT + 1):
        with pytest.raises(MeridianAttentionValidationError):
            MeridianAttentionItem(
                code="meridian_attempt_decision_pending",
                count=invalid,  # type: ignore[arg-type]
            )

    with pytest.raises(MeridianAttentionValidationError):
        MeridianAttentionItem(
            code="meridian_attempt_decision_pending",
            count=1,
            class_id=" class-01 ",
        )


def test_attention_definition_rejects_unknown_runtime_code() -> None:
    with pytest.raises(MeridianAttentionValidationError):
        attention_definition("meridian_export_pending")  # type: ignore[arg-type]


def test_summary_factory_sorts_by_destination_then_category_not_count() -> None:
    summary = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code="meridian_planning_review_stale",
                count=100,
            ),
            MeridianAttentionItem(
                code="meridian_source_superseded",
                count=1,
            ),
            MeridianAttentionItem(
                code="meridian_evidence_review_pending",
                count=2,
            ),
            MeridianAttentionItem(
                code="meridian_source_withdrawn",
                count=9,
            ),
        )
    )

    assert tuple(item.code for item in summary.items) == (
        "meridian_evidence_review_pending",
        "meridian_source_withdrawn",
        "meridian_source_superseded",
        "meridian_planning_review_stale",
    )


def test_summary_rejects_duplicate_codes_and_noncanonical_direct_order() -> None:
    duplicate = MeridianAttentionItem(
        code="meridian_native_value_unmapped",
        count=1,
    )
    with pytest.raises(MeridianAttentionValidationError):
        MeridianAttentionSummary(items=(duplicate, duplicate))

    with pytest.raises(MeridianAttentionValidationError):
        MeridianAttentionSummary(
            items=(
                MeridianAttentionItem(
                    code="meridian_planning_review_pending",
                    count=1,
                ),
                MeridianAttentionItem(
                    code="meridian_evidence_review_pending",
                    count=1,
                ),
            )
        )


def test_json_ready_projection_is_deterministic_and_privacy_minimal() -> None:
    summary = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code="meridian_academic_period_calculation_stale",
                count=3,
                class_id="class-01",
            ),
            MeridianAttentionItem(
                code="meridian_attempt_decision_pending",
                count=4,
                class_id="class-01",
            ),
        )
    )

    first = meridian_attention_summary_to_dict(summary)
    second = meridian_attention_summary_to_dict(summary)

    assert first == second
    assert first == {
        "schema_version": 2,
        "items": [
            {
                "code": "meridian_attempt_decision_pending",
                "label": "Applicable attempt decisions are pending",
                "count": 4,
                "count_unit": "attempt_decision_scopes",
                "destination_id": "attempt-decisions",
                "task_id": "attempt-decisions",
                "action_id": "open_attempt_decisions",
                "class_id": "class-01",
            },
            {
                "code": "meridian_academic_period_calculation_stale",
                "label": "Academic Period proficiency calculations are stale",
                "count": 3,
                "count_unit": "academic_period_proficiency_targets",
                "destination_id": "calculation-preview",
                "task_id": "calculation-preview",
                "action_id": "open_calculation_preview",
                "class_id": "class-01",
            },
        ],
    }
    rendered = repr(first)
    for forbidden in (
        "student_id",
        "student_name",
        "score",
        "percentage",
        "proficiency_level",
        "grouping_band",
        "digest",
    ):
        assert forbidden not in rendered
