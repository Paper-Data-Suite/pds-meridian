from __future__ import annotations

from pathlib import Path

from scripts.check_package import (
    ALLOWED_ENTRY_POINT_GROUPS,
    EXPECTED_OPERATIONS_ENTRY_POINT,
    EXPECTED_OPERATIONS_ENTRY_POINT_GROUP,
)

ATTENTION_RUNTIME_MODULES = (
    "meridian/academic_period_attention.py",
    "meridian/attention_provider.py",
    "meridian/attention_service.py",
    "meridian/pds_operations.py",
    "meridian/planning_attention.py",
    "meridian/proficiency_attention.py",
)

ATTENTION_TEST_SURFACES = (
    "tests/test_proficiency_attention_issue43.py",
    "tests/test_attention_core_adapter_issue43.py",
    "tests/test_planning_attention_issue43.py",
    "tests/test_academic_period_attention_issue43.py",
    "tests/test_attention_service_issue43.py",
    "tests/test_cli_attention_issue43.py",
    "tests/test_issue43_packaging_acceptance.py",
)


def test_issue43_operations_entry_point_is_exactly_release_guarded() -> None:
    assert EXPECTED_OPERATIONS_ENTRY_POINT_GROUP == (
        "paper_data_suite.module_operations"
    )
    assert EXPECTED_OPERATIONS_ENTRY_POINT == (
        "meridian.pds_operations:get_module_operations_profile"
    )
    assert ALLOWED_ENTRY_POINT_GROUPS == frozenset(
        {
            "console_scripts",
            "paper_data_suite.module_operations",
        }
    )

    checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    assert EXPECTED_OPERATIONS_ENTRY_POINT_GROUP in checker
    assert EXPECTED_OPERATIONS_ENTRY_POINT in checker


def test_issue43_attention_runtime_modules_are_release_guarded() -> None:
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    for member in ATTENTION_RUNTIME_MODULES:
        assert member in wheel_checker
        assert member in sdist_checker


def test_issue43_attention_tests_are_sdist_guarded() -> None:
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    for member in ATTENTION_TEST_SURFACES:
        assert member in sdist_checker
