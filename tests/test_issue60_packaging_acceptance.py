from __future__ import annotations

import tomllib
from pathlib import Path

from scripts.installed_qualification_matrix import (
    DEPENDENCY_MATRICES,
    TARGET_SHARED_ENVIRONMENT_COUNT,
)

ISSUE60_SDIST_MEMBERS = (
    "docs/architecture/cross-policy-adversarial-acceptance.md",
    "scripts/smoke_program_cross_policy_adversarial.py",
    "scripts/smoke_program_cross_policy_adversarial_reload.py",
    "scripts/smoke_test_cross_policy_adversarial_wheel.py",
    "tests/test_issue60_empty_incomplete_adversarial.py",
    "tests/test_issue60_attempt_scale_adversarial.py",
    "tests/test_issue60_group_lifecycle_adversarial.py",
    "tests/test_issue60_override_selection_adversarial.py",
    "tests/test_issue60_rounding_profile_adversarial.py",
    "tests/test_issue60_reporting_snapshot_adversarial.py",
    "tests/test_issue60_multi_adversity_operations.py",
    "tests/test_issue60_installed_acceptance.py",
    "tests/test_issue60_documentation_acceptance.py",
    "tests/test_issue60_packaging_acceptance.py",
)


def test_issue60_all_new_acceptance_assets_are_sdist_guarded() -> None:
    checker = Path("scripts/check_sdist.py").read_text(encoding="utf-8")
    for member in ISSUE60_SDIST_MEMBERS:
        assert member in checker


def test_issue60_does_not_expand_runtime_wheel_or_dependencies() -> None:
    wheel_checker = Path("scripts/check_package.py").read_text(encoding="utf-8")
    with Path("pyproject.toml").open("rb") as source:
        configuration = tomllib.load(source)
    project = configuration["project"]
    package_find = configuration["tool"]["setuptools"]["packages"]["find"]

    assert '"scripts/"' in wheel_checker
    assert '"tests/"' in wheel_checker
    assert package_find["include"] == ["meridian", "meridian.*"]
    assert project["dependencies"] == ["pds-core>=0.6.3,<0.7"]
    assert all(
        producer not in project["dependencies"]
        for producer in ("scoreform", "quillan", "pds-concord")
    )
    assert all(
        "paper-data-suite" not in dependency
        for dependency in project["dependencies"]
    )


def test_issue60_remains_reachable_through_one_central_validator() -> None:
    validator = Path("scripts/validate_repository.py").read_text(
        encoding="utf-8"
    )
    runner = Path("scripts/installed_qualification_runner.py").read_text(
        encoding="utf-8"
    )

    assert "scripts.installed_qualification_runner" in validator
    assert "run_issue60_cross_policy_prepared_smoke" in runner
    assert '"issue60-cross-policy-adversarial"' in runner
    assert "DependencyMatrixId.ALL_ADAPTERS" in runner
    assert TARGET_SHARED_ENVIRONMENT_COUNT == 6
    assert len(DEPENDENCY_MATRICES) == 6


def test_issue60_installed_program_pins_authenticated_sibling_versions() -> None:
    program = Path(
        "scripts/smoke_program_cross_policy_adversarial.py"
    ).read_text(encoding="utf-8")

    for token in (
        '"pds-core": "0.6.4"',
        '"scoreform": "0.12.1"',
        '"quillan": "0.10.5"',
        '"pds-concord": "0.3.0"',
    ):
        assert token in program
