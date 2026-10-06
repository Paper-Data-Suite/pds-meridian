from __future__ import annotations

from pathlib import Path

import pytest
from pds_core.academic_periods import AcademicPeriodRef
from pds_core.module_operations import (
    MODULE_OPERATIONS_CONTRACT_VERSION,
    ModuleOperationsRequest,
    invoke_module_attention,
    invoke_module_readiness,
)

from meridian.owner_actions import meridian_owner_action_definitions
from meridian.pds_operations import get_module_operations_profile
from meridian.reporting_snapshot_selection import (
    ReportingSnapshotSelectionValidationError,
    reporting_snapshot_selection_relative_path,
    reporting_snapshot_selection_scope_key,
)
from meridian.storage_path_keys import STORAGE_PATH_KEY_MAX_LENGTH, storage_path_key
from scripts.installed_qualification_matrix import (
    DEPENDENCY_MATRICES,
    TARGET_SHARED_ENVIRONMENT_COUNT,
    DependencyMatrixId,
    matrix_for,
)
from tests import test_issue59_readiness_provider as readiness_support


def test_issue61_meridian_owned_storage_keys_are_fixed_and_namespace_bound() -> None:
    long_identity = "semantic-" + ("x" * 10_000)
    first = storage_path_key("grade_item", long_identity)
    second = storage_path_key("reporting_snapshot", long_identity)

    assert len(first) == STORAGE_PATH_KEY_MAX_LENGTH == 67
    assert len(second) == STORAGE_PATH_KEY_MAX_LENGTH
    assert first != second
    assert "/" not in first
    assert "\\" not in first


def test_issue61_reporting_selector_scope_uses_one_bounded_opaque_key() -> None:
    period = AcademicPeriodRef("2026-2027", "mp1")
    key = reporting_snapshot_selection_scope_key(
        "english_12",
        "quarter_grade_report",
        period,
        1,
    )
    relative = reporting_snapshot_selection_relative_path(
        "english_12",
        "quarter_grade_report",
        period,
        1,
    )

    assert len(key) == STORAGE_PATH_KEY_MAX_LENGTH
    assert relative == (
        f"classes/english_12/modules/meridian/rs/{key}/current.json"
    )
    assert "quarter_grade_report" not in relative
    assert "2026-2027" not in relative
    assert "mp1" not in relative


def test_issue61_reporting_selector_rejects_path_escape_identity() -> None:
    with pytest.raises(ReportingSnapshotSelectionValidationError):
        reporting_snapshot_selection_scope_key(
            "english_12",
            "../escape",
            AcademicPeriodRef("2026-2027", "mp1"),
            1,
        )


def test_issue61_core_operations_readiness_and_attention_are_zero_write(
    tmp_path: Path,
) -> None:
    readiness_support._make_ready_class(tmp_path)
    before = readiness_support._snapshot(tmp_path)
    request = ModuleOperationsRequest(
        workspace_root=tmp_path,
        class_id=readiness_support.CLASS_ID,
        active_school_year="2026-2027",
    )
    profile = get_module_operations_profile()

    readiness = invoke_module_readiness(profile, request)
    attention = invoke_module_attention(profile, request)

    assert readiness.code == "module_operations.evaluated"
    assert readiness.report is not None
    assert readiness.report.ready is True
    assert attention.code == "module_operations.evaluated"
    assert attention.report is not None
    assert readiness_support._snapshot(tmp_path) == before


def test_issue61_operations_profile_exposes_exact_core_v1_capabilities() -> None:
    profile = get_module_operations_profile()

    assert profile.module_id == "meridian"
    assert profile.supported_core_operations_contract_versions == frozenset(
        {MODULE_OPERATIONS_CONTRACT_VERSION}
    )
    assert profile.readiness_provider is not None
    assert profile.attention_provider is not None


def test_issue61_installed_dependency_isolation_remains_exactly_six_matrices() -> None:
    assert TARGET_SHARED_ENVIRONMENT_COUNT == 6
    assert tuple(matrix.matrix_id for matrix in DEPENDENCY_MATRICES) == (
        DependencyMatrixId.CORE,
        DependencyMatrixId.SCOREFORM,
        DependencyMatrixId.QUILLAN,
        DependencyMatrixId.CONCORD,
        DependencyMatrixId.SCOREFORM_QUILLAN,
        DependencyMatrixId.ALL_ADAPTERS,
    )
    assert matrix_for(DependencyMatrixId.CORE).excluded_producers == (
        "scoreform",
        "quillan",
        "concord",
    )
    assert matrix_for(DependencyMatrixId.ALL_ADAPTERS).excluded_producers == ()


def test_issue61_owner_actions_are_deterministic_inert_routing_identity() -> None:
    first = meridian_owner_action_definitions()
    second = meridian_owner_action_definitions()

    assert first == second
    assert first
    for item in first:
        assert item.module_id == "meridian"
        assert item.action_id.startswith("open_")
        for value in (item.action_id, item.destination_id):
            assert "/" not in value
            assert "\\" not in value
            assert ":" not in value
            assert "--" not in value
