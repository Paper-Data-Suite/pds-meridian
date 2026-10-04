"""Issue #59 owner-action catalog and attention-routing acceptance."""

from __future__ import annotations

from pathlib import Path

import pytest
from pds_core.module_operations import ModuleOperationsRequest

from meridian.attention_provider import project_meridian_attention_to_core
from meridian.menu import TEACHER_MENU_TASKS
from meridian.owner_actions import (
    MERIDIAN_OWNER_ACTION_IDS,
    MERIDIAN_OWNER_DESTINATION_IDS,
    MERIDIAN_OWNER_MODULE_ID,
    MeridianOwnerActionValidationError,
    meridian_owner_action_definitions,
    owner_action_for_action_id,
    owner_action_for_destination,
)
from meridian.proficiency_attention import (
    MeridianAttentionItem,
    build_meridian_attention_summary,
    meridian_attention_definitions,
)
from meridian.teacher_workflows import TEACHER_WORKFLOW_TASK_IDS

EXPECTED_ACTIONS = (
    ("new-evidence", "open_new_evidence", "New Evidence"),
    ("grade-items", "open_grade_items", "Grade Items"),
    ("attempt-decisions", "open_attempt_decisions", "Attempt Decisions"),
    ("exclusions", "open_exclusions", "Exclusions"),
    ("standards-review", "open_standards_review", "Standards Review"),
    ("calculation-preview", "open_calculation_preview", "Calculation Preview"),
    ("preview-grades", "open_preview_grades", "Preview Grades"),
    ("snapshots", "open_snapshots", "Snapshots"),
    (
        "create-planning-signal",
        "open_create_planning_signal",
        "Create Planning Signal",
    ),
)


def test_owner_action_catalog_is_exact_unique_and_deterministic() -> None:
    first = meridian_owner_action_definitions()
    second = meridian_owner_action_definitions()

    assert first == second
    assert tuple(
        (item.destination_id, item.action_id, item.label)
        for item in first
    ) == EXPECTED_ACTIONS
    assert tuple(item.destination_id for item in first) == (
        MERIDIAN_OWNER_DESTINATION_IDS
    )
    assert tuple(item.action_id for item in first) == MERIDIAN_OWNER_ACTION_IDS
    assert tuple(item.order for item in first) == tuple(range(len(first)))
    assert len({item.destination_id for item in first}) == len(first)
    assert len({item.action_id for item in first}) == len(first)
    assert {item.module_id for item in first} == {MERIDIAN_OWNER_MODULE_ID}


def test_every_catalog_destination_is_a_declared_meridian_teacher_destination() -> None:
    legacy_destinations = set(TEACHER_WORKFLOW_TASK_IDS)
    main_menu_destinations = {task.task_id for task in TEACHER_MENU_TASKS}

    for item in meridian_owner_action_definitions():
        assert (
            item.destination_id in legacy_destinations
            or item.destination_id in main_menu_destinations
        )

    assert {
        item.destination_id
        for item in meridian_owner_action_definitions()
        if item.destination_id not in legacy_destinations
    } == {"preview-grades", "snapshots"}


def test_attention_definitions_consume_the_canonical_action_mapping() -> None:
    for definition in meridian_attention_definitions():
        action = owner_action_for_destination(definition.destination_id)
        assert definition.action_id == action.action_id


def test_grade_report_action_ids_from_issue58_are_unchanged() -> None:
    expected = {
        "meridian_grade_result_stale": "open_preview_grades",
        "meridian_reporting_publication_changed": "open_snapshots",
        "meridian_reporting_snapshot_refresh_needed": "open_snapshots",
        "meridian_reporting_snapshot_selection_pending": "open_snapshots",
    }

    observed = {
        definition.code: definition.action_id
        for definition in meridian_attention_definitions()
        if definition.code in expected
    }

    assert observed == expected


def test_all_attention_definitions_emit_catalog_owned_core_actions(
    tmp_path: Path,
) -> None:
    native = build_meridian_attention_summary(
        tuple(
            MeridianAttentionItem(code=definition.code, count=1)
            for definition in meridian_attention_definitions()
        )
    )

    report = project_meridian_attention_to_core(
        native,
        ModuleOperationsRequest(workspace_root=tmp_path.resolve()),
    )

    assert len(report.summaries) == len(meridian_attention_definitions())
    for summary in report.summaries:
        assert summary.action is not None
        assert summary.action.module_id == MERIDIAN_OWNER_MODULE_ID
        catalog_action = owner_action_for_action_id(summary.action.action_id)
        assert catalog_action.module_id == MERIDIAN_OWNER_MODULE_ID


def test_owner_actions_are_inert_identifiers_not_executable_payloads() -> None:
    forbidden_tokens = (
        "http://",
        "https://",
        "/",
        "\\",
        ":",
        ".py",
        "python ",
        "meridian ",
        "--",
    )

    for item in meridian_owner_action_definitions():
        assert item.action_id.startswith("open_")
        assert not any(character.isdigit() for character in item.action_id)
        for value in (item.action_id, item.destination_id):
            assert all(token not in value.casefold() for token in forbidden_tokens)


@pytest.mark.parametrize(
    "value",
    (
        "open_unknown",
        "meridian menu 4",
        "https://example.invalid/action",
        "../snapshots",
        "",
        None,
    ),
)
def test_unknown_action_ids_fail_closed_without_fallback(value: object) -> None:
    with pytest.raises(
        MeridianOwnerActionValidationError,
        match="Unsupported Meridian owner action ID",
    ):
        owner_action_for_action_id(value)


@pytest.mark.parametrize(
    "value",
    (
        "unknown-destination",
        "4",
        "meridian.cli:main",
        "../grade-items",
        "",
        None,
    ),
)
def test_unknown_destinations_fail_closed_without_fallback(value: object) -> None:
    with pytest.raises(
        MeridianOwnerActionValidationError,
        match="Unsupported Meridian owner destination",
    ):
        owner_action_for_destination(value)
