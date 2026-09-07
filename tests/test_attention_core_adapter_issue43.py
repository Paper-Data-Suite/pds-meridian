from __future__ import annotations

from pathlib import Path

import pytest
from pds_core.module_operations import (
    MODULE_OPERATIONS_CONTRACT_VERSION,
    ModuleAttentionReport,
    ModuleOperationsRequest,
    invoke_module_attention,
    invoke_module_readiness,
    validate_module_attention_report,
    validate_module_operations_profile,
)

from meridian.attention_provider import (
    MERIDIAN_ATTENTION_PARTIAL_NOTICE_CODE,
    MERIDIAN_ATTENTION_UNAVAILABLE_NOTICE_CODE,
    MERIDIAN_MODULE_ID,
    MeridianAttentionProviderError,
    project_meridian_attention_to_core,
)
from meridian.pds_operations import get_module_operations_profile
from meridian.proficiency_attention import (
    MeridianAttentionItem,
    build_meridian_attention_summary,
)


def test_core_projection_preserves_native_order_counts_and_owner_actions(
    tmp_path: Path,
) -> None:
    native = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code="meridian_planning_review_pending",
                count=2,
                class_id="class-01",
            ),
            MeridianAttentionItem(
                code="meridian_attempt_decision_pending",
                count=4,
                class_id="class-01",
            ),
        )
    )
    request = ModuleOperationsRequest(
        workspace_root=tmp_path.resolve(),
        class_id="class-01",
    )

    report = project_meridian_attention_to_core(native, request)

    assert report.evaluation == "evaluated"
    assert report.notices == ()
    assert tuple(summary.code for summary in report.summaries) == (
        "meridian_attempt_decision_pending",
        "meridian_planning_review_pending",
    )
    assert tuple(summary.count for summary in report.summaries) == (4, 2)
    assert tuple(summary.class_id for summary in report.summaries) == (
        "class-01",
        "class-01",
    )
    module_ids = tuple(
        summary.action.module_id for summary in report.summaries if summary.action
    )
    assert module_ids == (
        MERIDIAN_MODULE_ID,
        MERIDIAN_MODULE_ID,
    )
    action_ids = tuple(
        summary.action.action_id for summary in report.summaries if summary.action
    )
    assert action_ids == (
        "open_attempt_decisions",
        "open_create_planning_signal",
    )
    validate_module_attention_report(report, expected_module_id=MERIDIAN_MODULE_ID)


def test_core_projection_can_represent_successful_empty_attention(
    tmp_path: Path,
) -> None:
    report = project_meridian_attention_to_core(
        build_meridian_attention_summary(()),
        ModuleOperationsRequest(workspace_root=tmp_path.resolve()),
    )

    assert report == ModuleAttentionReport(evaluation="evaluated")


def test_core_projection_marks_partial_without_changing_evaluation(
    tmp_path: Path,
) -> None:
    native = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code="meridian_native_value_unmapped",
                count=1,
            ),
        )
    )

    report = project_meridian_attention_to_core(
        native,
        ModuleOperationsRequest(workspace_root=tmp_path.resolve()),
        partial=True,
    )

    assert report.evaluation == "evaluated"
    assert len(report.summaries) == 1
    assert tuple(notice.code for notice in report.notices) == (
        MERIDIAN_ATTENTION_PARTIAL_NOTICE_CODE,
    )


def test_core_projection_rejects_class_context_leak(tmp_path: Path) -> None:
    native = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code="meridian_membership_review_pending",
                count=1,
                class_id="class-02",
            ),
        )
    )

    with pytest.raises(MeridianAttentionProviderError):
        project_meridian_attention_to_core(
            native,
            ModuleOperationsRequest(
                workspace_root=tmp_path.resolve(),
                class_id="class-01",
            ),
        )


def test_operations_profile_is_core_v1_attention_only_and_validates(
    tmp_path: Path,
) -> None:
    profile = get_module_operations_profile()

    assert profile.module_id == MERIDIAN_MODULE_ID
    assert profile.supported_core_operations_contract_versions == frozenset(
        {MODULE_OPERATIONS_CONTRACT_VERSION}
    )
    assert profile.attention_provider is not None
    assert profile.readiness_provider is None
    assert validate_module_operations_profile(profile) is profile

    readiness = invoke_module_readiness(
        profile,
        ModuleOperationsRequest(workspace_root=tmp_path.resolve()),
    )
    assert readiness.code == "module_operations.capability_absent"


def test_installed_provider_is_fail_closed_without_workspace() -> None:
    result = invoke_module_attention(
        get_module_operations_profile(),
        ModuleOperationsRequest(),
    )

    assert result.code == "module_operations.evaluation_unavailable"
    assert result.provider_call_attempted is True
    assert result.provider_call_succeeded is True
    assert result.result_validation == "passed"
    assert isinstance(result.report, ModuleAttentionReport)
    assert result.report.evaluation == "unavailable"
    assert result.report.summaries == ()
    assert tuple(notice.code for notice in result.report.notices) == (
        MERIDIAN_ATTENTION_UNAVAILABLE_NOTICE_CODE,
    )


def test_core_projection_is_privacy_minimal(tmp_path: Path) -> None:
    native = build_meridian_attention_summary(
        (
            MeridianAttentionItem(
                code="meridian_grade_item_calculation_stale",
                count=3,
                class_id="class-01",
            ),
        )
    )
    report = project_meridian_attention_to_core(
        native,
        ModuleOperationsRequest(
            workspace_root=tmp_path.resolve(),
            class_id="class-01",
        ),
    )

    rendered = repr(report)
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


def test_pyproject_registers_exact_module_operations_entry_point() -> None:
    text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert '[project.entry-points."paper_data_suite.module_operations"]' in text
    assert (
        'meridian = "meridian.pds_operations:get_module_operations_profile"'
        in text
    )
