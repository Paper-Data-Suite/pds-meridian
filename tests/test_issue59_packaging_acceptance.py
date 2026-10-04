"""Issue #59 packaging and dependency guards."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_readiness_runtime_and_slice_tests_are_release_guarded() -> None:
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    sdist_checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")

    assert "meridian/readiness_provider.py" in wheel_checker
    assert "meridian/readiness_provider.py" in sdist_checker
    assert "meridian/owner_actions.py" in wheel_checker
    assert "meridian/owner_actions.py" in sdist_checker
    assert "tests/test_issue59_readiness_provider.py" in sdist_checker
    assert "tests/test_issue59_owner_actions.py" in sdist_checker
    assert "tests/test_issue59_backup_boundary.py" in sdist_checker
    assert "tests/test_issue59_packaging_acceptance.py" in sdist_checker


def test_issue59_keeps_existing_core_floor_and_no_suite_dependency() -> None:
    with Path("pyproject.toml").open("rb") as source:
        project = tomllib.load(source)["project"]

    assert project["dependencies"] == ["pds-core>=0.6.3,<0.7"]
    assert all(
        "paper-data-suite" not in dependency
        for dependency in project["dependencies"]
    )


def test_public_launcher_and_single_operations_entry_point_remain_exact() -> None:
    with Path("pyproject.toml").open("rb") as source:
        project = tomllib.load(source)["project"]

    assert project["scripts"] == {"meridian": "meridian.cli:main"}
    assert project["entry-points"]["paper_data_suite.module_operations"] == {
        "meridian": "meridian.pds_operations:get_module_operations_profile"
    }
